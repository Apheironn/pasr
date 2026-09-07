# A vhs tape that records the README demo GIF.
#
#   1. install vhs (https://github.com/charmbracelet/vhs) + ffmpeg
#        winget install charmbracelet.vhs        (Windows)
#        brew install vhs                        (macOS)
#   2. make sure `pasr` is on PATH  (pip install -e .  or  pipx install pasr-mcp)
#   3. clone the demo repo once:
#        bash scripts/gen_examples.sh            (checks out .eval-checkouts/requests)
#   4. vhs scripts/demo.tape                     -> docs/assets/demo.gif
#   5. in README.md swap  docs/assets/hero.svg  ->  docs/assets/demo.gif
#
# Deterministic: no live typing to fumble, re-run any time the output changes.

Output docs/assets/demo.gif

Set Shell bash
Set FontSize 15
Set Width 1180
Set Height 680
Set Padding 20
Set TypingSpeed 35ms
Set Theme "Catppuccin Mocha"

Hide
Type "cd .eval-checkouts/requests" Enter
Ctrl+L
Show

Sleep 700ms
Type `pasr explain "how are redirects resolved and followed" src --budget 3000 --no-write`
Sleep 400ms
Enter
Sleep 4s
Type "# one tool call · 42,768 -> 2,718 tokens · a receipt for every line"
Sleep 2500ms
