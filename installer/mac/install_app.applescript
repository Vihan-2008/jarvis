-- "Install JARVIS": what a person double-clicks in the Mac download. Everything it installs is inside it
-- (Contents/Resources/jarvis-app: the app's files, install.sh and JARVIS's own Python), so it works wherever macOS runs
-- it from: a download opened where it lies is run from a hidden, read-only copy of the app alone ("app translocation"),
-- and anything beside the app would not be found. It runs install.sh without a Terminal window, shows that it is
-- working, says plainly what went wrong if anything did, and opens JARVIS at the end. Nothing else needs installing.
--
-- For GitHub's Mac test: JARVIS_INSTALL_ANSWERED=yes takes its questions as answered, and JARVIS_INSTALL_ARGS adds
-- options for install.sh (another install folder, for instance). Run with osascript on Contents/Resources/Scripts/main.scpt.
on run
	set answered to (system attribute "JARVIS_INSTALL_ANSWERED") is "yes"
	set here to POSIX path of (path to me)
	if here ends with ".scpt" then
		set resources to do shell script "cd \"$(dirname " & quoted form of here & ")/..\" && pwd"
	else
		if here does not end with "/" then set here to here & "/"
		set resources to here & "Contents/Resources"
	end if
	set installer to resources & "/jarvis-app/install.sh"
	try
		do shell script "test -f " & quoted form of installer
	on error
		if answered then error "install.sh is not inside Install JARVIS: " & installer
		display alert "Some of JARVIS's files are missing" message "Download JARVIS again, then double-click Install JARVIS." as critical
		return
	end try
	if not answered then
		try
			display dialog "JARVIS will be installed for you on this Mac:" & return & return & "• the app goes in Applications," & return & "• your notes go in Documents/JARVIS Vault," & return & "• it starts in the background when you log in (you can turn that off in its Settings)." & return & return & "It takes a minute or two, and nothing else needs to be installed." buttons {"Cancel", "Install"} default button "Install" cancel button "Cancel" with title "Install JARVIS" with icon note
		on error number -128
			return
		end try
	end if
	set logFile to "/tmp/jarvis-install-" & (do shell script "date +%s") & ".log"
	set progress total steps to -1
	set progress description to "Installing JARVIS…"
	set progress additional description to "This takes a minute or two."
	set extra to system attribute "JARVIS_INSTALL_ARGS"
	try
		with timeout of 3600 seconds
			do shell script "/bin/bash " & quoted form of installer & " --quiet --no-obsidian --wake-word --login --open " & extra & " > " & quoted form of logFile & " 2>&1"
		end timeout
	on error errText number errNumber
		if answered then error "install.sh failed (" & errNumber & "); its report: " & logFile
		set lastLines to do shell script "grep -v '^[[:space:]]*$' " & quoted form of logFile & " 2>/dev/null | tail -n 6 || true"
		display alert "JARVIS could not be installed" message lastLines & return & return & "Fix what it says, then double-click Install JARVIS again: it carries on where it stopped and keeps your settings and chats." & return & return & "The full report is in " & logFile as critical
		return
	end try
	set progress description to "JARVIS is installed."
	if answered then return "installed; report in " & logFile
	display dialog "JARVIS is installed, and it is opening now." & return & return & "Next time, open it from Applications (or Launchpad). When macOS asks whether JARVIS may use the microphone, or control your computer, choose Allow: JARVIS asks only when it needs one, and says why." buttons {"Done"} default button "Done" with title "Install JARVIS" with icon note
end run
