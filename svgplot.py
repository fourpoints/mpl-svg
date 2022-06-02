import io
import matplotlib
import matplotlib.pyplot as plt
import random
import re
import string
import sys
import xml.etree.ElementTree as ET
from itertools import chain
from matplotlib import figure, rcParams
from pathlib import Path

# Matplotlib SVG backend source
# https://github.com/matplotlib/matplotlib/blob/main/lib/matplotlib/backends/backend_svg.py
# This library is not bad, but the underlying structure of matplotlib
# is lacking, so data is incomplete. E.g. no "axis-frame" class etc.
# This makes the generated CSS is tailwind-like, meaning very modular,
# in a class="regular bold text" instead of class="axis-title" (or w/e)
# It's possible to make some inference, since id="axes-2" exists; but
# this may not be reliable information, and is implementation dependent.

# Prevent crash if backend is unsupported
matplotlib.use("svg")

# Draw text as text, not as path
# Importing this library will override this value,
# but it's the preferable default here.
plt.rcParams["svg.fonttype"] = "none"


# Util functions
if sys.version_info <= (3, 9):
    def with_stem(self, stem):
        """Return a new path with the stem changed."""
        return self.with_name(stem + self.suffix)
    Path.with_stem = with_stem


# When will this be added to itertools
def ilen(it): return sum(1 for _ in it)


def make_uid(length=8):
    alphabet = string.ascii_lowercase + string.digits
    return "".join(random.choices(alphabet, k=length))


# Components
class StyleMap:
    # Singleton class; subclass to set more parameters
    _global = {
        # uncomment to include
        "stroke-linecap": "butt",
        "stroke-linejoin": "round",
    }

    _text = {
        "stroke": "none",
        "fill": "#000000",
    }

    stroke = {
        "#ffffff": "primary",
        "#000000": "primary-text",
        "#cccccc": "secondary",

        # Default matplotlib color scheme
        "#1f77b4": "blue",
        "#ff7f0e": "orange",
        "#2ca02c": "green",
        "#d62728": "red",
        "#9467bd": "purple",
        "#8c564b": "brown",
        "#e377c2": "pink",
        "#7f7f7f": "grey",
        "#bcbd22": "olive",
        "#17becf": "cyan",
    }

    fill = {
        "none": "no-fill",
        "#ffffff": "bg",
    }

    stroke_width = {
        "0.8": "thin",
        "1.5": "thick",
    }

    stroke_line_join = {
        "round": "rounded",
        "miter": "miter",
    }

    stroke_line_cap = {
        "butt": "butt",
        "square": "square",
    }

    font = {
        "10px 'sans-serif'": "regular",
    }

    text_anchor = {
        "start": "left-align",
        "middle": "center-align",
        "end": "right-align",
    }

    attributes = {
        "fill": fill,
        "stroke": stroke,
        "stroke-width": stroke_width,
        "stroke-linejoin": stroke_line_join,
        "stroke-linecap": stroke_line_cap,
        "font": font,
        "text-anchor": text_anchor,
    }

    @staticmethod
    def parse(string):
        if string == "":
            return
        for rule in string.split(";"):
            yield tuple(map(str.strip, rule.split(":")))

    @classmethod
    def classify(cls, style):
        classes = []
        for attr, value in cls._global.items():
            class_ = cls.attributes[attr][value]
            classes.append(class_)

        for attr, value in cls.parse(style):
            class_ = cls.attributes[attr][value]
            classes.append(class_)
        return " ".join(classes)

    @classmethod
    def tostring(cls):
        ruleset = []
        for attr, group in cls.attributes.items():
            for rule, selector in group.items():
                selector_rule = f".{selector} {{ {attr}: {rule}; }}"
                ruleset.append(selector_rule)

        text_rule = "; ".join(
            f"{attr}: {rule}" for attr, rule in cls._text.items()
        )

        ruleset.append(f".{'text'} {{ {text_rule}; }}")

        return "".join(ruleset)


class Namespaces:
    # Wrapper class for namespaces
    @staticmethod
    def _namespaces(source):
        if isinstance(source, str):
            source = io.StringIO(source)
        return dict(
            node for _event, node in ET.iterparse(source, events=['start-ns'])
        )

    @staticmethod
    def register_namespaces(namespaces):
        for prefix, uri in namespaces.items():
            ET.register_namespace(prefix, uri)

    @classmethod
    def fromstring(cls, text):
        namespaces = cls._namespaces(text)
        cls.register_namespaces(namespaces)
        return namespaces

    @classmethod
    def frompath(cls, path):
        namespaces = cls._namespaces(path)
        cls.register_namespaces(namespaces)
        return namespaces


class SVG:
    def __init__(self, el, namespaces=None, id=None):
        if id is None: id = make_uid()

        self.el = el
        self.namespaces = namespaces
        self.id = id

    @classmethod
    def fromstring(cls, text, parser=None, id=None):
        namespaces = Namespaces.fromstring(text)
        return cls(ET.fromstring(text, parser), namespaces, id)

    @classmethod
    def frompath(cls, path, parser=None, id=None):
        namespaces = Namespaces.frompath(path)
        return cls(ET.parse(path, parser).getroot(), namespaces, id)

    @property
    def style(self):
        return self.el.find("defs/style", namespaces=self.namespaces)

    def slim(self):
        for c in self.el.iter():
            c.text = c.text.strip() if c.text is not None else None
            c.tail = None

        # " a  b c  " -> "a b c"
        _slim = lambda string: re.sub(r"^\s+|\s+$|\s+(?=\s)", "", string)
        for c in self.el.iter():
            for att in c.keys():
                c.set(att, _slim(c.get(att)))

    def svg2(self):
        # deprecated in svg 2.0
        # https://developer.mozilla.org/en-US/docs/Web/SVG/Attribute/xlink:href
        xlink = "{http://www.w3.org/1999/xlink}"
        N = len(xlink)
        def _fix(el, name):
            if name.startswith(xlink):
                el.set(name[N:], el.attrib.pop(name))

        for el in self.iter():
            for key in el.keys():
                _fix(el, key)

    def uid(self):
        # Since ids are repeated in other svgs
        # we have to insert a svg-unique id

        def insert(string, ins):
            # This code is too clever (that's a bad thing)
            # It inserts `ins` after the last # and before the last -
            # insert("hello-world", "what") --> "hello-what-world"
            # insert("#hey", "world") --> #world-hey
            # insert("#a-b-c", "x") --> "#a-b-x-c"
            string = string.replace("_", "-")

            parts = []
            prefix, sharp, string = string.rpartition("#")
            parts.extend([prefix, sharp])

            before, dash, after = string.rpartition("-")
            parts.extend([before, dash, ins, "-", after])

            return "".join(filter(None, parts))

        for el in self.iter("[@id]"):
            id_ = insert(el.get("id"), self.id)
            el.set("id", id_)

        for el in self.iter("[@href]"):
            href = insert(el.get("href"), self.id)
            el.set("href", href)

        for el in self.iter("[@clip-path]"):
            clip = insert(el.get("clip-path"), self.id)
            el.set("clip-path", clip)


    @staticmethod
    def set_none(el, attr, value):
        attrs = chain(el.get(attr, "").split(" "), value.split(" "))
        attrs = sorted(set(attrs))
        new_value = " ".join(filter(None, attrs))
        if new_value:
            el.set(attr, new_value)

    def classify(self):
        for el in self.iter("path"):
            self.set_none(el, "class", StyleMap.classify(el.attrib.pop("style", "")))

        for el in self.iter("use"):
            self.set_none(el, "class", StyleMap.classify(el.attrib.pop("style", "")))

        # If text is path
        for el in self.iter("[@id]"):
            if el.get("id").startswith("DejaVuSans"):
                print("Hhhhhh")
                self.set_none(el, "class", "text")

        # If text is text
        for el in self.iter("text"):
            self.set_none(el, "class", StyleMap.classify(el.attrib.pop("style", "")))
            self.set_none(el, "class", "text")

        assert ilen(self.iter("[@style]")) == 0

        self.style.text = StyleMap.tostring()

    @classmethod
    def _iter(cls, el, tag, namespaces):
        yield from el.iterfind(tag, namespaces)
        yield from chain.from_iterable(cls._iter(c, tag, namespaces) for c in el)


    def iter(self, tag="*"):
        yield from self._iter(self.el, tag, self.namespaces)

    def tostring(self):
        return ET.tostring(self.el, encoding="unicode")


# Helper classes
def savefig(plot, path, id=None):
    f = io.StringIO()
    plot.savefig(f, format="svg")
    svg = SVG.fromstring(f.getvalue(), id)

    svg.classify()
    svg.slim()
    svg.svg2()
    svg.uid()

    path = Path(path)
    path.write_text(svg.tostring(), encoding="utf-8")
    print("saved")


def minify(path, id=None):
    svg = SVG.frompath(path, id)

    svg.classify()
    svg.slim()
    svg.svg2()
    svg.uid()

    path = Path(path)
    path = path.with_stem(path.stem + "-min")
    path.write_text(svg.tostring(), encoding="utf-8")


if __name__ == "__main__":
    def test_plot():
        plt.plot([1, 2, 3, 4], [1, 4, 9, 16], gid="abc")
        plt.text(1, 1, "HELLO")
        plt.xlabel("t")
        plt.ylabel("y")
        with plt.style.context("classic"):
            plt.plot([5, 6, 7], [25, 36, 49], gid="def")

    def test():
        test_plot()

        file = io.StringIO()
        plt.savefig(file, format="svg")

        return file.getvalue()

    test_plot()

    # svg = SVG.fromstring(xml)
    # svg.classify()
    # svg.slim()
    # svg.svg2()
    # svg.uid()

    case = Path("~/Pictures/test.svg").expanduser()
    # case.write_text(svg.tostring(), encoding="utf-8")

    savefig(plt, case)
    # minify(case)
