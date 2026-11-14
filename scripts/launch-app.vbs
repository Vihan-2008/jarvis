' Opens JARVIS with no console window. It finds the app from where this file is (the folder above "scripts"),
' so it works wherever JARVIS was put. Python: the one named in the file ".python" beside the app (written by the
' installer), otherwise "pythonw.exe" as Windows finds it.
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
root = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
python = "pythonw.exe"
If fso.FileExists(root & "\.python") Then
  Set named = fso.OpenTextFile(root & "\.python", 1)
  If Not named.AtEndOfStream Then
    line = Trim(named.ReadLine)
    If Len(line) > 0 And fso.FileExists(line) Then python = line
  End If
  named.Close
End If
extra = ""
For Each argument In WScript.Arguments
  extra = extra & " " & argument
Next
sh.Environment("PROCESS")("PYTHONPATH") = root
sh.CurrentDirectory = root
sh.Run """" & python & """ -m jcc.desktop" & extra, 0, False
