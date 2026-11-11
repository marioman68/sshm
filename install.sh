#!/usr/bin/env bash

TARGET_DIR="$HOME/.local/bin"
TARGET_FILE="$TARGET_DIR/sshm"

echo "Starting sshm installation..."

# 1. Check if the source script actually exists in this folder
if [ ! -f "sshm" ]; then
    echo "❌ Error: 'sshm' script not found in the current directory."
    echo "Make sure you are in the correct folder and the file is named 'sshm'."
    exit 1
fi

# Extract the new version number (fallback to 'unknown' if you forgot to add it)
NEW_VERSION=$(grep -m 1 '^VERSION=' sshm | cut -d'"' -f2 | cut -d"'" -f2)
NEW_VERSION=${NEW_VERSION:-unknown}

# 2. Check if already installed and handle version comparison
if [ -f "$TARGET_FILE" ]; then
    OLD_VERSION=$(grep -m 1 '^VERSION=' "$TARGET_FILE" | cut -d'"' -f2 | cut -d"'" -f2)
    OLD_VERSION=${OLD_VERSION:-unknown}

    if [ "$NEW_VERSION" == "$OLD_VERSION" ]; then
        read -rp "ℹ️  Version vOLD_VERSION is already installed. Reinstall anyway? (y/N): " confirm
        if [[ ! "$confirm" =~ ^[Yy] ]]; then
            echo "Installation canceled."
            exit 0
        fi
    else
        echo "✨ Update detected!"
        echo "   Current installed version: v$OLD_VERSION"
        echo "   New version available:     v$NEW_VERSION"
        read -rp "Do you want to replace the current installation? (Y/n): " confirm
        if [[ "$confirm" =~ ^[Nn] ]]; then
            echo "Installation canceled."
            exit 0
        fi
    fi
fi

# 3. Create target directory if it doesn't exist
if [ ! -d "$TARGET_DIR" ]; then
    echo "📁 Creating directory: $TARGET_DIR"
    mkdir -p "$TARGET_DIR"
fi

# 4. Attempt to copy and set permissions
echo "⚙️  Copying script to $TARGET_DIR..."

if cp sshm "$TARGET_FILE" 2>/dev/null && chmod +x "$TARGET_FILE" 2>/dev/null; then
    echo "✔ Installed locally without needing sudo."
else
    echo "🔒 Permission denied. Escalating to sudo to overwrite the file..."
    
    sudo cp sshm "$TARGET_FILE"
    sudo chmod +x "$TARGET_FILE"
    
    # Fix the ownership of the file so your normal user owns it again!
    sudo chown $(id -u):$(id -g) "$TARGET_FILE"
    
    echo "✔ Installed and fixed file ownership using sudo."
fi

# 5. Final verification check
if [ -x "$TARGET_FILE" ]; then
    echo "🚀 sshm (v$NEW_VERSION) is ready! You can now run 'sshm' from anywhere."
else
    echo "❌ Something went wrong. Installation failed."
    exit 1
fi
