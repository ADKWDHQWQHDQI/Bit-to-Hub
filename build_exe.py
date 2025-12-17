"""
Build script for creating standalone .exe using PyInstaller
Run this script to build the distribution package for clients.
"""
import PyInstaller.__main__
import os
import shutil
import sys

def clean_previous_builds():
    """Remove previous build artifacts"""
    print("=" * 70)
    print("CLEANING PREVIOUS BUILDS")
    print("=" * 70)
    
    folders_to_clean = ['build', 'dist', '__pycache__']
    
    for folder in folders_to_clean:
        if os.path.exists(folder):
            print(f"Removing {folder}/...")
            shutil.rmtree(folder)
    
    # Remove .spec files
    for file in os.listdir('.'):
        if file.endswith('.spec'):
            print(f"Removing {file}...")
            os.remove(file)
    
    print("✅ Cleanup complete\n")


def build_executable():
    """Build the executable using PyInstaller"""
    print("=" * 70)
    print("BUILDING EXECUTABLE")
    print("=" * 70)
    
    # PyInstaller configuration
    pyinstaller_args = [
        'main.py',                          # Main script
        '--onefile',                         # Single executable file
        '--name=PRMigrationTool',           # Output name
        '--console',                         # Keep console window
        
        # Include data files (templates)
        '--add-data=config.template.yaml;.',
        '--add-data=user_mapping.template.yaml;.',
        
        # Hidden imports (dependencies that PyInstaller might miss)
        '--hidden-import=yaml',
        '--hidden-import=requests',
        '--hidden-import=github',
        '--hidden-import=dateutil',
        '--hidden-import=dateutil.parser',
        '--hidden-import=tenacity',
        '--hidden-import=urllib3',
        
        # Collect all submodules
        '--collect-all=github',
        '--collect-all=yaml',
        
        # Optimization
        '--noconfirm',                       # Replace output without confirmation
        '--clean',                           # Clean cache before building
        
        # Optional: Add icon (uncomment if you have an icon file)
        # '--icon=app.ico',
    ]
    
    print("\nRunning PyInstaller with configuration:")
    print(f"  - Single file mode: ✅")
    print(f"  - Console mode: ✅")
    print(f"  - Output name: PRMigrationTool.exe")
    print(f"  - Including templates: config.template.yaml, user_mapping.template.yaml")
    print()
    
    try:
        PyInstaller.__main__.run(pyinstaller_args)
        print("\n" + "=" * 70)
        print("✅ BUILD SUCCESSFUL!")
        print("=" * 70)
        print(f"\nExecutable location: {os.path.abspath('dist/PRMigrationTool.exe')}")
        print("\nNext steps:")
        print("  1. Test the executable: cd dist && PRMigrationTool.exe")
        print("  2. Package for client: Copy dist/PRMigrationTool.exe + USAGE.txt")
        print("=" * 70)
        
    except Exception as e:
        print(f"\n❌ BUILD FAILED: {e}")
        sys.exit(1)


def create_distribution_folder():
    """Create a distribution folder with all files needed for client"""
    print("\n" + "=" * 70)
    print("CREATING DISTRIBUTION PACKAGE")
    print("=" * 70)
    
    dist_folder = 'client_distribution'
    
    if os.path.exists(dist_folder):
        shutil.rmtree(dist_folder)
    
    os.makedirs(dist_folder)
    
    # Copy executable
    exe_path = 'dist/PRMigrationTool.exe'
    if os.path.exists(exe_path):
        shutil.copy(exe_path, dist_folder)
        print(f"✅ Copied: PRMigrationTool.exe")
    
    # Copy usage instructions
    if os.path.exists('USAGE.txt'):
        shutil.copy('USAGE.txt', dist_folder)
        print(f"✅ Copied: USAGE.txt")
    
    # Copy templates (optional - for reference)
    if os.path.exists('config.template.yaml'):
        shutil.copy('config.template.yaml', dist_folder)
        print(f"✅ Copied: config.template.yaml (reference)")
    
    if os.path.exists('user_mapping.template.yaml'):
        shutil.copy('user_mapping.template.yaml', dist_folder)
        print(f"✅ Copied: user_mapping.template.yaml (reference)")
    
    print(f"\n✅ Distribution package created in: {os.path.abspath(dist_folder)}")
    print("\nContents:")
    for item in os.listdir(dist_folder):
        size = os.path.getsize(os.path.join(dist_folder, item))
        print(f"  - {item} ({size:,} bytes)")
    
    print("\n" + "=" * 70)
    print("READY FOR CLIENT DELIVERY")
    print("=" * 70)
    print(f"\nZip the '{dist_folder}' folder and send to your client.")
    print("Client only needs to:")
    print("  1. Extract the zip file")
    print("  2. Run PRMigrationTool.exe")
    print("  3. Enter their credentials when prompted")
    print("=" * 70)


def main():
    """Main build process"""
    print("\n" + "=" * 70)
    print("  BITBUCKET TO GITHUB PR MIGRATION - BUILD SCRIPT")
    print("=" * 70)
    print("\nThis script will:")
    print("  1. Clean previous builds")
    print("  2. Build standalone .exe with PyInstaller")
    print("  3. Create distribution package for client")
    print("\n" + "=" * 70)
    
    response = input("\nProceed with build? (yes/no): ").strip().lower()
    if response not in ['yes', 'y']:
        print("Build cancelled.")
        return
    
    print()
    
    # Step 1: Clean
    clean_previous_builds()
    
    # Step 2: Build
    build_executable()
    
    # Step 3: Create distribution package
    create_distribution_folder()
    
    print("\n🎉 ALL DONE! 🎉\n")


if __name__ == "__main__":
    main()
