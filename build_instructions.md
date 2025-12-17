================================================================================
BITBUCKET TO GITHUB PR MIGRATION TOOL
BUILD INSTRUCTIONS FOR DEVELOPERS
================================================================================

This guide explains how to build the standalone .exe file for client distribution.

================================================================================
OVERVIEW
================================================================================

The tool is packaged as a single .exe file using PyInstaller. Clients receive
only the executable - they cannot access the source code. The tool prompts for
credentials interactively on first run.

================================================================================
PREREQUISITES
================================================================================

1. Python 3.8 or higher installed
2. Git (to clone/manage the repository)
3. Windows OS (for building Windows .exe)

================================================================================
STEP-BY-STEP BUILD PROCESS
================================================================================

## STEP 1: PREPARE THE BUILD ENVIRONMENT

Open Command Prompt or PowerShell and navigate to the project directory:

cd c:\bitbucket-github-pr-migration

Create and activate a virtual environment (recommended):

python -m venv venv
venv\Scripts\activate

You should see (venv) in your command prompt.

## STEP 2: INSTALL BUILD DEPENDENCIES

Install all required packages including PyInstaller:

pip install -r build_requirements.txt

This installs:

- All runtime dependencies (requests, PyGithub, PyYAML, etc.)
- PyInstaller (the tool that creates the .exe)

## STEP 3: VERIFY PROJECT STRUCTURE

Ensure your project has these files:

REQUIRED:
✓ main.py (modified with interactive prompts)
✓ clients/ (Bitbucket & GitHub API clients)
✓ models/ (PR data models)
✓ utils/ (helper utilities)
✓ config.template.yaml
✓ user_mapping.template.yaml
✓ build_exe.py
✓ USAGE.txt

BACKED UP:
📦 config.yaml.backup (your original config - DO NOT DISTRIBUTE!)
📦 user_mapping.yaml.backup (your original mappings)

## STEP 4: BUILD THE EXECUTABLE

Run the build script:

python build_exe.py

The script will:

1. Clean previous build artifacts
2. Run PyInstaller to create the .exe
3. Create a client_distribution folder with all files

Build time: 2-5 minutes depending on your system.

Expected output:

- client_distribution/ (ready-to-ship package with PRMigrationTool.exe)

## STEP 5: TEST THE EXECUTABLE

IMPORTANT: Test on a clean system or in a separate folder without Python!

Test steps:

1. Copy the .exe to a test location:

   mkdir C:\test_migration
   copy client_distribution\PRMigrationTool.exe C:\test_migration
   cd C:\test_migration

2. Run the executable:

   PRMigrationTool.exe

3. Verify:
   ✓ Configuration wizard appears
   ✓ Can enter credentials (sensitive ones are hidden as \*\*\*\*)
   ✓ Creates config.yaml
   ✓ Connection test works
   ✓ Migration runs successfully

4. Test with dry-run:

   PRMigrationTool.exe --dry-run

5. Test connection validation:

   PRMigrationTool.exe --test-connection

## STEP 6: PACKAGE FOR CLIENT DISTRIBUTION

The build script creates a 'client_distribution' folder with:

📦 client_distribution/
├── PRMigrationTool.exe (10-20 MB)
├── USAGE.txt (client instructions)
└── config.template.yaml (optional reference)

To distribute:

1. Zip the client_distribution folder:

   (Right-click → Send to → Compressed folder)

   OR use command:

   powershell Compress-Archive -Path client_distribution -DestinationPath PRMigrationTool.zip

2. Send PRMigrationTool.zip to your client

3. Client extracts and runs PRMigrationTool.exe

================================================================================
WHAT THE CLIENT RECEIVES
================================================================================

The client gets:
✅ Single .exe file (no Python installation needed)
✅ USAGE.txt with clear instructions
✅ Interactive credential setup (no YAML editing)
✅ Automatic config file generation

The client CANNOT:
❌ See your source code (compiled to bytecode)
❌ Access your credentials (not included)
❌ Modify the application logic

================================================================================
CLIENT USAGE FLOW
================================================================================

1. Client extracts the zip file
2. Double-clicks PRMigrationTool.exe
3. First run triggers configuration wizard:
   - Enter Bitbucket workspace & repository (visible)
   - Choose auth method (OAuth or Token)
   - Enter credentials (hidden as \*\*\*\* for security)
   - Enter GitHub owner & repository (visible)
   - Enter GitHub token (hidden as \*\*\*\*)
4. Tool creates config.yaml automatically
5. Client runs migration:
   - PRMigrationTool.exe --test-connection (verify)
   - PRMigrationTool.exe --dry-run (test)
   - PRMigrationTool.exe (actual migration)

================================================================================
TROUBLESHOOTING BUILD ISSUES
================================================================================

ISSUE: "PyInstaller command not found"
→ Solution: pip install pyinstaller

ISSUE: "Module not found during build"
→ Solution: Add to --hidden-import in build_exe.py

ISSUE: ".exe file is very large (>50MB)"
→ Solution: Normal. Includes Python interpreter + dependencies.

ISSUE: "Antivirus blocks the .exe"
→ Solution: This is common for PyInstaller exes. Consider code signing
or add to antivirus whitelist during testing.

ISSUE: "Runtime error: No module named 'X'"
→ Solution: Add to --hidden-import list in build_exe.py and rebuild

ISSUE: "Cannot find template files"
→ Solution: Verify --add-data paths in build_exe.py match your structure

================================================================================
UPDATING THE TOOL
================================================================================

When you make changes to the code:

1. Edit the source files (main.py, clients/, etc.)
2. Test changes locally:

   python main.py --dry-run

3. Increment version (optional - edit build_exe.py or main.py)
4. Rebuild:

   python build_exe.py

5. Re-test the new .exe
6. Re-package for distribution

================================================================================
ADVANCED: BUILD OPTIONS
================================================================================

CUSTOMIZING THE BUILD:

Edit build_exe.py to customize:

1. Add an icon:

   - Create app.ico file
   - Uncomment: '--icon=app.ico' in build_exe.py

2. Hide console window:

   - Change '--console' to '--noconsole'
   - (Not recommended - users can't see progress)

3. Include additional files:

   - Add: '--add-data=myfile.txt;.'

4. Exclude modules (reduce size):

   - Add: '--exclude-module=tkinter'

5. Multi-file build (instead of single exe):
   - Remove '--onefile' flag
   - Results in folder with multiple files but faster startup

ALTERNATIVE BUILD TOOLS:

1. Nuitka (better performance, smaller size):

   pip install nuitka
   python -m nuitka --standalone --onefile main.py

2. cx_Freeze (cross-platform):

   pip install cx_Freeze
   python setup.py build

================================================================================
SECURITY CONSIDERATIONS
================================================================================

SOURCE CODE PROTECTION:
✓ PyInstaller compiles to bytecode (basic protection)
✓ Code is embedded in .exe (not easily readable)
✗ Can be decompiled with effort (not foolproof)

For stronger protection:

- Use Nuitka (compiles to native C)
- Use PyArmor (code obfuscation)
- Add licensing/activation system

CREDENTIALS SECURITY:
✓ No credentials in the .exe
✓ Client enters their own credentials
✓ Config stored locally on client machine
⚠ Remind clients to protect config.yaml (contains tokens)

================================================================================
DISTRIBUTION CHECKLIST
================================================================================

Before sending to client:

[ ] Built and tested .exe on clean system
[ ] Verified configuration wizard works
[ ] Tested actual migration with test repositories
[ ] Included USAGE.txt with clear instructions
[ ] Removed all your credentials from package
[ ] Backed up your config files (.backup files)
[ ] Tested on target Windows version
[ ] Prepared support plan for client issues
[ ] Documented any known limitations
[ ] Created invoice for the migration service 💰

================================================================================
QUICK REFERENCE - BUILD COMMANDS
================================================================================

# Setup environment

python -m venv venv
venv\Scripts\activate
pip install -r build_requirements.txt

# Build .exe

python build_exe.py

# Test locally

python main.py --test-connection

# Test .exe

dist\PRMigrationTool.exe --test-connection

# Package for client

powershell Compress-Archive -Path client_distribution -DestinationPath PRMigrationTool.zip

================================================================================
SUPPORT & MAINTENANCE
================================================================================

Client Support:

- Provide USAGE.txt with clear instructions
- Direct them to check logs/ folder for errors
- Common issues documented in USAGE.txt

Maintenance:

- Keep dependencies updated (pip list --outdated)
- Rebuild periodically for security patches
- Version your releases (v1.0, v1.1, etc.)

================================================================================
CONGRATULATIONS! 🎉
================================================================================

You now have a production-ready .exe for client distribution!

Your client receives a professional tool without accessing your source code.
They simply enter credentials and the migration runs automatically.

Questions? Check the troubleshooting section above or contact the maintainer.

================================================================================
