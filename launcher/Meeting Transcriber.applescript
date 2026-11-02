-- Starts the Meeting Transcriber server in the background (if it isn't running
-- yet) and opens it in the default browser. Rebuild the .app with
-- launcher/build.sh.

set projectDir to "/Users/bobi/Desktop/Meeting_Summary"
set appURL to "http://localhost:5001"
set checkCmd to "curl -s -o /dev/null -w '%{http_code}' " & appURL & " || true"

-- Friendly error if dependencies were never installed.
if (do shell script "test -d " & quoted form of (projectDir & "/.venv") & " && echo yes || echo no") is "no" then
	display dialog "Meeting Transcriber isn't set up yet." & return & return & "Open Terminal in the project folder and run ./setup.sh once, then try again." buttons {"OK"} default button 1 with icon caution
	return
end if

if (do shell script checkCmd) is not "200" then
	-- Only the server goes to the background, with all its output redirected;
	-- otherwise "do shell script" waits for it to finish. MT_NO_BROWSER stops
	-- run.sh from opening a second tab -- this script opens the browser below.
	do shell script "cd " & quoted form of projectDir & "; MT_NO_BROWSER=1 nohup ./run.sh > data/server.log 2>&1 < /dev/null &"
	set started to false
	-- Generous timeout: the Whisper model is loaded into memory at boot.
	repeat 240 times
		delay 0.5
		if (do shell script checkCmd) is "200" then
			set started to true
			exit repeat
		end if
	end repeat
	if not started then
		display dialog "Meeting Transcriber didn't start. Details are in data/server.log in the project folder." buttons {"OK"} default button 1 with icon caution
		return
	end if
end if

open location appURL
