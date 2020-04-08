#!/usr/bin/env python3

import os, re, sys


debug = {
    # print method names during the initial method-selection phase
    "print_method_names_instantly": False
}

def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)

def main():
    if not os.path.exists("README.md"):
        eprint("Please run from root of mtasa-blue folder.")
        sys.exit(1)

    with open("README.md", "r") as f:
        if not f.readline().startswith("## Multi Theft Auto: San Andreas"):
            eprint("Please run from root of mtasa-blue folder.")
            sys.exit(1)

    filesToCheck = []

    # We assume that only the folders mentioned below are problematic. Verify using:
    #   grep -iR 'void _declspec(naked)' Client | cut -d":" -f1 | cut -d"/" -f2 | sort | uniq
    for folder in ["Client/game_sa", "Client/multiplayer_sa"]:
        for fpath in os.listdir(folder):
            fpath = os.path.join(folder, fpath)
            if os.path.isdir(fpath):
                eprint("Unexpected subfolder", fpath)
                sys.exit(1)
            filesToCheck.append(fpath)

    methodCount = 0
    methods = []
    for fpath in filesToCheck:
        with open(fpath, 'r') as f:
            methods.extend(extractMethods(fpath, f))

    processMethods(methods)

    badCount = 0
    methodCount = len(methods)
    longestPath = 0
    longestName = 0
    for method in methods:
        error = method['error']
        if len(error) > 0:
            badCount += 1
            longestPath = max(longestPath, len(os.path.basename(method["fpath"])))
            longestName = max(longestName, len(method["name"]))

    print("CODE ", "File".ljust(longestPath), "Method".ljust(longestName), "Context")
    print("-----", "".ljust(longestPath, "-"), "".ljust(longestName, "-"), "-------")
    for method in methods:
        error = method['error']
        if len(error) > 0:
            print(error[0],os.path.basename(method["fpath"]).ljust(longestPath), method["name"].ljust(longestName), *error[1:])



    eprint()
    eprint("----------")
    eprint("Statistics")
    eprint("----------")
    eprint("- {} naked methods found".format(methodCount))
    eprint("- {} naked methods with non-asm found".format(badCount))
    eprint("- Completion: {:.2f}%".format((methodCount-badCount) * 100 / methodCount))

def trimPrefix(text, prefix, ins=False):
    origText = text
    if ins:
        text = text.lower()
        prefx = prefix.lower()

    if text.startswith(prefix):
        return origText[len(prefix):]
    return origText


def extractMethods(fpath, f):
    """
    extractMethods works by looking for lines that roughly match this:
        - start with `void _declspec(naked)`, followed by
        - a line with a single open brace without leading whitespace, followed by
        - a line leading with at least 4 spaces and a character, followed by
        - anything, until the following line is found
        - a line with a single close brace without leading whitespace
    """

    """
    We stipulate that those lines must either start with:
        static void
    or:
        void

    We stipulate that those lines must immediately be followed with:
        HOOK_

    We keep reading from "HOOK_" onwards until we find a special character, giving us our method name.

    We stipulate that the next line (rstripped) contains exactly "{".

    We sti

    """
    methods = []

    stage = "findStart"
    processingComment = False

    method: dict

    for line in f:
        # We don't care about trailing spaces in all scenarios
        # Also cut out comments on the same line
        line: str = line.split("//")[0].rstrip()

        lineLower = line.lower()

        if stage == "findStart":
            if processingComment:
                eprint("File", fpath, " hit illegal processingComment")
                sys.exit(1)

            # New method object
            method = {
                "name": None,
                "fpath": fpath,
                "lines": [],
                "error": [],
            }

            # Find a line containing `_declspec(naked)` or `__declspec(naked)`
            if "_declspec(naked)" not in lineLower:
                continue

            # Remove _declspec(naked) from the string, and strip spaces.
            # This allows us to accept `void` being after the declspec
            lineLower = lineLower.replace("__declspec(naked)", "").replace("_declspec(naked)", "").strip()

            if not (lineLower.startswith("static void ") or lineLower.startswith("void ")):
                eprint("File", fpath, "contains odd line (should start with `static void` or `void`):", line)
                sys.exit(1)

            if not lineLower.endswith("()"):
                eprint("File", fpath, "contains odd line (should end with `()`):", line)
                sys.exit(1)

            methodName = line[:-2]
            for prefix in ["static ", "void ", "_", "_", "declspec(naked) "]:
                methodName = trimPrefix(methodName, prefix, True)

            if debug["print_method_names_instantly"]:
                eprint("Found method name", methodName)
            method["name"] = methodName
            stage = "findOpen"

        elif stage == "findOpen":
            if line != "{":
                eprint("File", fpath, "method", method["name"], "contains odd line:", line)
                sys.exit(1)
            stage = "findCloseInitial"

        elif stage == "findCloseInitial" or stage == "findCloseGrep":
            cutline = line.lstrip()
            # Kinda ignore lines with leading whitespace
            if cutline != line:
                # initial line must have at least one character
                if stage == "findCloseInitial":
                    if cutline == "":
                        eprint("File", fpath, "method", method["name"], "contains odd empty line")
                        sys.exit(1)
                    elif line == "}":
                        eprint("File", fpath, "method", method["name"], "contains odd line:", line)
                        sys.exit(1)

                    stage = "findCloseGrep"

            # Skip commented lines
            if cutline.startswith("//"):
                continue

            # We've found the closing line!
            if line == "}":
                # cut out comments and edge space
                method['lines'] = comment_remover("\n".join(method['lines'])).strip().splitlines()

                methods.append(method)
                stage = "findStart"
                continue

            method["lines"].append(line)

    return methods


def processMethods(methods):
    error = []
    name, fpath, lines = "", "", ""
    previous = {}

    for method in methods:
        if len(error) > 0:
            previous['error'] = error

        # print("Processing ", method['name'])
        error = []
        previous = method
        name, fpath, lines = method['name'], method['fpath'], method['lines']

        # Needs to have _asm, open brace, some code, and closing brace
        if len(lines) <= 3:
            error = ["M-NUM"]
            continue

        # Needs to have _asm, some code, and closing brace
        if lines[0].lstrip() != "_asm":
            error = ["M-1ST", lines[0]]
            continue

        # Second line should contain just a left bracket, ignoring leading space
        openBrace = lines[1]
        if openBrace.lstrip() != "{":
            error = ["M-2ND", lines[0]]
            continue

        # Last line should contain right bracket with same whtiespace as left bracket
        closeBrace = openBrace.replace("{", "}")
        if lines[-1] != closeBrace:
            error = ["M-END", lines[-1], "expected", closeBrace]
            continue

        # Now we know there's an error if any of the intermediate lines contain a brace
        sublines = lines[2:-1]
        prevLine = ""
        for i, line in enumerate(sublines):
            if "{" in line or "}" in line:
                nextLine = sublines[i+1].strip() if i+1 < len(sublines) else ""
                error = ["M-BAD", prevLine + " \\n " + line + " \\n " + nextLine]
                break
            prevLine = line.strip()

# From https://stackoverflow.com/a/241506/1517394
def comment_remover(text):
    def replacer(match):
        s = match.group(0)
        if s.startswith('/'):
            return " " # note: a space and not an empty string
        else:
            return s
    pattern = re.compile(
        r'//.*?$|/\*.*?\*/|\'(?:\\.|[^\\\'])*\'|"(?:\\.|[^\\"])*"',
        re.DOTALL | re.MULTILINE
    )
    return re.sub(pattern, replacer, text)






if __name__ == "__main__":
    main()
