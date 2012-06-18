#!/usr/bin/env python
import sys
import os.path
from subprocess import Popen, PIPE
import re
import json

from r2.lib.translation import iter_langs

try:
    from pylons import g, c, config
except ImportError:
    STATIC_ROOT = None
else:
    STATIC_ROOT = config["pylons.paths"]["static_files"]

# STATIC_ROOT will be None if pylons is uninitialized
if not STATIC_ROOT:
    REDDIT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    STATIC_ROOT = os.path.join(os.path.dirname(REDDIT_ROOT), "build/public")

script_tag = '<script type="text/javascript" src="{src}"></script>\n'
inline_script_tag = '<script type="text/javascript">{content}</script>\n'

class ClosureError(Exception): pass
class ClosureCompiler(object):
    def __init__(self, jarpath, args=None):
        self.jarpath = jarpath
        self.args = args or []

    def _run(self, data, out=PIPE, args=None, expected_code=0):
        args = args or []
        p = Popen(["java", "-jar", self.jarpath] + self.args + args,
                stdin=PIPE, stdout=out, stderr=PIPE)
        out, msg = p.communicate(data)
        if p.returncode != expected_code:
            raise ClosureError(msg)
        else:
            return out, msg
    
    def compile(self, data, dest, args=None):
        """Run closure compiler on a string of source code `data`, writing the
        result to output file `dest`. A ClosureError exception will be raised if
        the operation is unsuccessful."""
        return self._run(data, dest, args)[0]

class Source(object):
    """An abstract collection of JavaScript code."""
    def get_source(self):
        """Return the full JavaScript source code."""
        raise NotImplementedError
    
    def use(self):
        """Return HTML to insert the JavaScript source inside a template."""
        raise NotImplementedError

    @property
    def dependencies(self):
        raise NotImplementedError

    @property
    def outputs(self):
        raise NotImplementedError

class FileSource(Source):
    """A JavaScript source file on disk."""
    def __init__(self, name):
        self.name = name
    
    def get_source(self):
        return open(self.path).read()

    @property
    def path(self):
        """The path to the source file on the filesystem."""
        return os.path.join(STATIC_ROOT, "static", "js", self.name)

    def use(self):
        from r2.lib.template_helpers import static
        path = [g.static_path, self.name]
        if g.uncompressedJS:
            path.insert(1, "js")
        return script_tag.format(src=static(os.path.join(*path)))

    @property
    def dependencies(self):
        return [self.path]

class Module(Source):
    """A module of JS code consisting of a collection of sources."""
    def __init__(self, name, *sources, **kwargs):
        self.name = name
        self.should_compile = kwargs.get('should_compile', True)
        self.sources = []
        sources = sources or (name,)
        for source in sources:
            if not isinstance(source, Source):
                if 'prefix' in kwargs:
                    source = os.path.join(kwargs['prefix'], source)
                source = FileSource(source)
            self.sources.append(source)

    def get_source(self):
        return ";".join(s.get_source() for s in self.sources)

    def extend(self, module):
        self.sources.extend(module.sources)

    @property
    def path(self):
        """The destination path of the module file on the filesystem."""
        return os.path.join(STATIC_ROOT, "static", self.name)

    def build(self, closure):
        print >> sys.stderr, "Compiling {0}...".format(self.name),
        with open(self.path, "w") as out:
            if self.should_compile:
                closure.compile(self.get_source(), out)
            else:
                out.write(self.get_source())
        print >> sys.stderr, " done."

    def use(self):
        from r2.lib.template_helpers import static
        if g.uncompressedJS:
            return "".join(source.use() for source in self.sources)
        else:
            return script_tag.format(src=static(self.name))

    @property
    def dependencies(self):
        deps = []
        for source in self.sources:
            deps.extend(source.dependencies)
        return deps

    @property
    def outputs(self):
        if self.should_compile:
            return [self.path]
        else:
            return []

class StringsSource(Source):
    """A virtual source consisting of localized strings from r2.lib.strings."""
    def __init__(self, lang=None, keys=None, prepend="r.strings = "):
        self.lang = lang
        self.keys = keys
        self.prepend = prepend

    def get_source(self):
        from pylons.i18n import get_lang
        from r2.lib import strings, translation

        if self.lang:
            old_lang = get_lang()
            translation.set_lang(self.lang)

        data = {}
        if self.keys is not None:
            for key in self.keys:
                data[key] = strings.strings[key]
        else:
            data = dict(strings.strings)
        
        output = self.prepend + json.dumps(data) + "\n"

        if self.lang:
            translation.set_lang(old_lang)

        return output

    def use(self):
        return inline_script_tag.format(content=self.get_source())

class LocalizedModule(Module):
    """A module that is localized with r2.lib.strings.
    
    References to `r.strings.<string>` are parsed out of the module source.
    A StringsSource is created and included which contains localized versions
    of the strings referenced in the module.
    """

    @staticmethod
    def languagize_path(path, lang):
        path_name, path_ext = os.path.splitext(path)
        return path_name + "." + lang + path_ext

    def build(self, closure):
        Module.build(self, closure)

        reddit_source = open(self.path).read()
        string_keys = re.findall("r\.strings\.([\w$_]+)", reddit_source)

        print >> sys.stderr, "Creating language-specific files:"
        for lang, unused in iter_langs():
            strings = StringsSource(lang, string_keys)
            source = strings.get_source()
            lang_path = LocalizedModule.languagize_path(self.path, lang)

            # make sure we're not rewriting a different mangled file
            # via symlink
            if os.path.islink(lang_path):
                os.unlink(lang_path)

            with open(lang_path, "w") as out:
                print >> sys.stderr, "  " + lang_path
                out.write(reddit_source+source)

    def use(self):
        from pylons.i18n import get_lang
        from r2.lib.template_helpers import static
        embed = Module.use(self)
        if g.uncompressedJS:
            return embed + StringsSource().use()
        else:
            url = LocalizedModule.languagize_path(self.name, get_lang()[0])
            return script_tag.format(src=static(url))

    @property
    def outputs(self):
        for lang, unused in iter_langs():
            yield LocalizedModule.languagize_path(self.path, lang)

class JQuery(Module):
    version = "1.7.2"

    def __init__(self, cdn_src=None):
        local_jquery_path = os.path.join("js", "lib", "jquery-%s.min.js" % self.version)
        Module.__init__(self, local_jquery_path, should_compile=False)
        self.cdn_src = cdn_src or "http://ajax.googleapis.com/ajax/libs/jquery/%s/jquery" % self.version
    
    def build(self, closure):
        pass

    def use(self):
        from r2.lib.template_helpers import static
        if c.secure or c.user.pref_local_js:
            return script_tag.format(src=static(self.name))
        else:
            ext = ".js" if g.uncompressedJS else ".min.js"
            return script_tag.format(src=self.cdn_src+ext)

module = {}

module["jquery"] = JQuery()

module["reddit"] = LocalizedModule("reddit.js",
    "lib/json2.js",
    "lib/store.js",
    "lib/jquery.cookie.js",
    "lib/jquery.url.js",
    "jquery.reddit.js",
    "base.js",
    "utils.js",
    "ui.js",
    "login.js",
    "flair.js",
    "analytics.js",
    "reddit.js",
)

module["mobile"] = LocalizedModule("mobile.js",
    module["reddit"],
    "lib/jquery.lazyload.js",
    "compact.js"
)

module["button"] = Module("button.js",
    "lib/jquery.cookie.js",
    "jquery.reddit.js",
    "blogbutton.js"
)

module["sponsored"] = Module("sponsored.js",
    "lib/ui.core.js",
    "lib/ui.datepicker.js",
    "sponsored.js"
)

module["flot"] = Module("jquery.flot.js",
    "lib/jquery.flot.js"
)

def use(*names):
    return "\n".join(module[name].use() for name in names)

def load_plugin_modules():
    from r2.lib.plugin import PluginLoader
    for plugin in PluginLoader.available_plugins():
        plugin_cls = plugin.load()
        plugin_cls().add_js(module)

commands = {}
def build_command(fn):
    def wrapped(*args):
        load_plugin_modules()
        fn(*args)
    commands[fn.__name__] = wrapped
    return wrapped

@build_command
def enumerate_modules():
    for name, m in module.iteritems():
        if m.should_compile:
            print name

@build_command
def dependencies(name):
    for dep in module[name].dependencies:
        print dep

@build_command
def enumerate_outputs(*names):
    if names:
        modules = [module[name] for name in names]
    else:
        modules = module.itervalues()

    for m in modules:
        for output in m.outputs:
            print output

@build_command
def build_module(name):
    closure = ClosureCompiler("r2/lib/contrib/closure_compiler/compiler.jar")
    module[name].build(closure)

if __name__ == "__main__":
    commands[sys.argv[1]](*sys.argv[2:])
