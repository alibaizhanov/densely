# vhs demo tape for densely — regenerate with: vhs assets/demo.tape (from repo root)
# Records a real Claude Code session: compress a 1,600-line incident log via the
# densely MCP tools, search inside the payload, expand the exact lines.
# Post-processed to final GIF speed with ffmpeg (see assets/make_gif.sh).
Output assets/demo_raw.mp4

Set FontSize 14
Set Width 1080
Set Height 640
Set Theme "Catppuccin Mocha"
Set Padding 10
Set TypingSpeed 25ms

Env PATH "/opt/homebrew/bin:/Users/alibaizhanov/.local/bin:/Library/Frameworks/Python.framework/Versions/3.12/bin:/usr/bin:/bin"

Hide
Type `unset CLAUDECODE CLAUDE_CODE_ENTRYPOINT CLAUDE_CODE_SESSION_ID CLAUDE_CODE_CHILD_SESSION CLAUDE_PID CLAUDE_CODE_MESSAGING_SOCKET CLAUDE_CODE_EXECPATH CLAUDE_JOB_DIR CLAUDE_EFFORT AI_AGENT && clear`
Enter
Sleep 500ms
Show
Type `claude --allowedTools "mcp__densely__compress_file,mcp__densely__search,mcp__densely__expand"`
Enter
Wait+Screen@60s /shortcuts/
Sleep 2s
Type "Don't read /tmp/incident.log raw - it's huge. Compress it with densely, then search the payload for the E500 error and expand the lines right around it."
Sleep 1s
Enter
Wait+Screen@300s /NullPointerException/
Sleep 30s
