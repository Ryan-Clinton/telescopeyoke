# Set up telescopeyoke on Windows 10 or 11.
#
#   .\install.ps1
#
# If Windows says running scripts is disabled, run it this once as:
#   powershell -ExecutionPolicy Bypass -File .\install.ps1
#
# It installs the Python libraries for the Python found on PATH and creates
# config.toml. It needs no administrator rights and changes no system setting.
# The camera driver, the plate solver and ffmpeg are installed by hand; it
# lists them at the end.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "Python was not found. Install 64-bit Python 3.11 or newer from python.org,"
    Write-Host "ticking 'Add python.exe to PATH', then run this again."
    exit 1
}
$found = python -c "import struct, sys; print('%d.%d.%d %d %d' % (sys.version_info[:3] + (struct.calcsize('P') * 8, sys.version_info >= (3, 11))))"
$version, $bits, $newEnough = $found -split " "
if ($newEnough -ne "1") {
    Write-Host "Python $version found; 3.11 or newer is needed."
    exit 1
}
if ($bits -ne "64") {
    Write-Host "Python $version is $bits-bit. The camera's library needs 64-bit Python."
    exit 1
}
Write-Host "Python $version, 64-bit: OK"

# "python -m pip", not "pip": pip on PATH may belong to a different Python.
python -m pip install .
if ($LASTEXITCODE -ne 0) {
    Write-Host "The Python libraries did not install; see the messages above."
    exit 1
}
Write-Host "Python libraries: installed"

if (Test-Path config.toml) {
    Write-Host "config.toml: already there, left alone"
} else {
    Copy-Item config.example.toml config.toml
    Write-Host "config.toml: created from the example. Edit it and put in your own location."
}

# Where Altair's SDK files go; they are not part of this project.
New-Item -ItemType Directory -Force vendor\altair | Out-Null

Write-Host @"

Done. Still to do by hand:

  [ ] config.toml: your location. Write Windows paths with forward slashes,
      such as "C:/Program Files/astap".
  [ ] Camera: download "Altair Camera SDK" from altairastro.help (you have
      to register there) and leave the zip in Downloads. Then plug the
      camera in and run:  python camera_setup.py
  [ ] Plate solver: ASTAP's command-line program (astap_cli.exe) and the D20
      star database, both in C:\Program Files\astap.
  [ ] ffmpeg, with ffplay, on PATH: for the webcam and the focusing tones.
      Name the webcam under [webcam] in config.toml.

Then try, with nothing plugged in:
    python tonight.py --demo
    python mount.py --demo goto M27

and check what is ready with:
    python doctor.py
"@
