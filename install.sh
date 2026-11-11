#!/usr/bin/env bash

TARGET_DIR="$HOME/.local/bin"
TARGET_FILE="$TARGET_DIR/sshm"

# Color Palette Definitions
C_RESET="\e[0m"
C_BOLD="\e[1m"
C_RED="\e[31m"
C_GREEN="\e[32m"
C_YELLOW="\e[33m"
C_CYAN="\e[36m"

echo -e "${C_CYAN}${C_BOLD}[ INFO ] Starting sshm installation...${C_RESET}"

# 1. Check if the source script actually exists in this folder
if [ ! -f "sshm" ]; then
    echo -e "${C_RED}[ FAIL ] Error: 'sshm' script not found in the current directory.${C_RESET}"
    echo -e "${C_RED}         Make sure you are in the correct folder and the file is named 'sshm'.${C_RESET}"
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
        echo -ne "${C_YELLOW}[INPUT ] Version $OLD_VERSION is already installed. Reinstall anyway? (y/N): ${C_RESET}"
        read -r confirm
        if [[ ! "$confirm" =~ ^[Yy] ]]; then
            echo -e "${C_YELLOW}[ INFO ] Installation canceled.${C_RESET}"
            exit 0
        fi
    else
        echo -e "${C_GREEN}${C_BOLD}[ INFO ] Update detected!${C_RESET}"
        echo -e "         Current installed version: ${C_YELLOW}$OLD_VERSION${C_RESET}"
        echo -e "         New version available:     ${C_GREEN}$NEW_VERSION${C_RESET}"
        echo -ne "${C_BOLD}[INPUT ] Do you want to replace the current installation? (Y/n): ${C_RESET}"
        read -r confirm
        if [[ "$confirm" =~ ^[Nn] ]]; then
            echo -e "${C_YELLOW}[ INFO ] Installation canceled.${C_RESET}"
            exit 0
        fi
    fi
fi

# 3. Create target directory if it doesn't exist
if [ ! -d "$TARGET_DIR" ]; then
    echo -e "${C_CYAN}[ INFO ] Creating directory: $TARGET_DIR${C_RESET}"
    mkdir -p "$TARGET_DIR"
fi

# 4. Attempt to copy and set permissions
echo -e "${C_CYAN}[ INFO ] Copying script to $TARGET_DIR...${C_RESET}"

if cp sshm "$TARGET_FILE" 2>/dev/null && chmod +x "$TARGET_FILE" 2>/dev/null; then
    echo -e "${C_GREEN}[  OK  ] Installed locally without needing sudo.${C_RESET}"
else
    echo -e "${C_YELLOW}[ WARN ] Permission denied. Escalating to sudo to overwrite the file...${C_RESET}"
    
    sudo cp sshm "$TARGET_FILE"
    sudo chmod +x "$TARGET_FILE"
    
    # Fix the ownership of the file so your normal user owns it again
    sudo chown $(id -u):$(id -g) "$TARGET_FILE"
    
    echo -e "${C_GREEN}[  OK  ] Installed and fixed file ownership using sudo.${C_RESET}"
fi

# 5. Final verification check
if [ -x "$TARGET_FILE" ]; then
    echo -e "${C_GREEN}${C_BOLD}[  OK  ] sshm (v$NEW_VERSION) is ready! You can now run 'sshm' from anywhere.${C_RESET}"
else
    echo -e "${C_RED}[ FAIL ] Something went wrong. Installation failed.${C_RESET}"
    exit 1
fi
