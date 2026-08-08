# vhs demo tape for densely — regenerate with: vhs demo.tape
Output demo.gif

Set FontSize 15
Set Width 900
Set Height 400
Set Theme "Catppuccin Mocha"
Set Padding 12
Set TypingSpeed 35ms

Type "# 1,515-line incident log — 74,464 tokens of context"
Enter
Type "wc -l /tmp/incident.log"
Enter
Sleep 1.5s

Type "python3 densely.py stats /tmp/incident.log"
Enter
Sleep 3.5s

Type "# compress it: 78% fewer tokens, byte-exact recovery guaranteed"
Enter
Type "python3 densely.py compress /tmp/incident.log -o incident.dense"
Enter
Sleep 2.5s

Type "# need line 507 back? expand exactly what you need"
Enter
Type "python3 densely.py decompress incident.dense | sed -n '507p'"
Enter
Sleep 3s

Type "# full round-trip is byte-identical (sha256-verified)"
Enter
Type "python3 densely.py decompress incident.dense -o restored.log"
Enter
Sleep 1s
Type "cmp restored.log /tmp/incident.log && echo IDENTICAL"
Enter
Sleep 3.5s
