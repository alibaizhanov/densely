# vhs demo tape for densely — regenerate with: vhs demo.tape
# Records a real Claude Code session calling the densely MCP tools.
Output demo.gif

Set FontSize 15
Set Width 1000
Set Height 340
Set Theme "Catppuccin Mocha"
Set Padding 12
Set TypingSpeed 30ms

Env PATH "/Users/alibaizhanov/.local/bin:/Library/Frameworks/Python.framework/Versions/3.12/bin:/opt/homebrew/bin:/usr/bin:/bin"

Type `claude -p "The incident log /tmp/incident.log is huge. Compress it with densely instead of reading it, then show me line 507 exactly." --allowedTools "mcp__densely__compress_file,mcp__densely__expand"`
Enter
Wait+Screen@180s /E500/
Sleep 6s
