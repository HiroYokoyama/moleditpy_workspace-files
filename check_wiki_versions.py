"""Compare plugin versions across the three places they are written down.

  repo source (PLUGIN_VERSION)  vs  REGISTRY/plugins.json  vs  the wiki pages

Run from anywhere:  python G:/DEV_MAIN/check_wiki_versions.py
Exits non-zero when anything disagrees, so it also works as a pre-push check.
"""

import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
REGISTRY = os.path.join(ROOT, "moleditpy-plugins", "REGISTRY", "plugins.json")
WIKI = os.path.join(ROOT, "moleditpy-plugins.wiki")

VERSION_RE = re.compile(r"""^PLUGIN_VERSION\s*=\s*["']([^"']+)["']""", re.M)
# "documents **Name v1.2.3**" (EN) / "**Name v1.2.3** を対象に" (JP)
FOOTER_RE = re.compile(r"\*\*(.+?) v([0-9][^*]*?)\*\*")


def read(path):
    with io.open(path, encoding="utf-8", errors="replace") as handle:
        return handle.read()


def source_version(plugin):
    """PLUGIN_VERSION as the code says it, from whichever tree ships the plugin.

    External plugins live in a sibling checkout named after their projectUrl;
    bundled ones are a path inside moleditpy-plugins relative to REGISTRY/.
    """
    project_url = plugin.get("projectUrl") or ""
    if not project_url:
        bundled = plugin.get("downloadUrl") or ""
        if bundled.startswith(".."):
            path = os.path.normpath(os.path.join(os.path.dirname(REGISTRY), bundled))
            if os.path.isfile(path):
                found = VERSION_RE.search(read(path))
                return found.group(1) if found else None
        return None
    repo = os.path.join(ROOT, project_url.rstrip("/").rsplit("/", 1)[-1])
    if not os.path.isdir(repo) or os.path.normcase(repo) == os.path.normcase(ROOT):
        return None
    for base, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in (".git", "tests", "build", "dist")]
        for name in files:
            if name.endswith(".py"):
                found = VERSION_RE.search(read(os.path.join(base, name)))
                if found:
                    return found.group(1)
    return None


def main():
    plugins = json.loads(read(REGISTRY))
    plugins = plugins["plugins"] if isinstance(plugins, dict) else plugins
    visible = [p for p in plugins if p.get("visible", True)]
    catalogues = {name: read(os.path.join(WIKI, name))
                  for name in ("Official-Plugins.md", "Official-Plugins-JP.md")}
    problems = []

    for plugin in visible:
        name, registry_version = plugin["name"], plugin.get("version")
        in_code = source_version(plugin)
        if in_code and in_code != registry_version:
            problems.append("%s: source %s != registry %s"
                            % (name, in_code, registry_version))
        for page, text in catalogues.items():
            if name.replace(" Plugin", "") not in text:
                problems.append("%s: absent from %s" % (name, page))

    for page in sorted(os.listdir(WIKI)):
        if not page.startswith("Plugin-"):
            continue
        found = FOOTER_RE.search(read(os.path.join(WIKI, page)).rsplit("-----", 1)[-1])
        if not found:
            problems.append("%s: no version footer" % page)
            continue
        name, wiki_version = found.group(1), found.group(2).strip()
        current = [p.get("version") for p in visible
                   if p["name"].replace(" Plugin", "") == name]
        if current and wiki_version != current[0]:
            problems.append("%s: wiki %s != registry %s" % (page, wiki_version, current[0]))

    print("\n".join(problems) if problems
          else "%d visible plugins: source, registry and wiki all agree." % len(visible))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
