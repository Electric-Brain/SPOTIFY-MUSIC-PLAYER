Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = scriptDir

pyExe = "pythonw"
knownPy = "C:\Users\Gautam\AppData\Local\Programs\Python\Python311\pythonw.exe"
If fso.FileExists(knownPy) Then
    pyExe = """" & knownPy & """"
End If

WshShell.Run pyExe & " """ & scriptDir & "\now_playing.py""", 0, False
