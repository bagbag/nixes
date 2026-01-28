{
  writeShellApplication,
  nvd,
  ...
}:
writeShellApplication {
  name = "diff-gen";
  runtimeInputs = [ nvd ];

  text = ''
    # Define standard paths
    CURRENT_RUNNING="/run/current-system"
    BOOT_DEFAULT="/nix/var/nix/profiles/system"
    PROFILE_BASE="/nix/var/nix/profiles/system"

    case $# in
      0)
        # No args: Compare what's running now vs what will boot next
        echo "Comparing: Running System -> Next Boot"
        FROM=$CURRENT_RUNNING
        TO=$BOOT_DEFAULT
        ;;
      1)
        # 1 arg: Compare what's running now vs a specific generation
        echo "Comparing: Running System -> Generation $1"
        FROM=$CURRENT_RUNNING
        TO="''${PROFILE_BASE}-$1-link"
        ;;
      2)
        # 2 args: Compare two specific generations
        echo "Comparing: Generation $1 -> Generation $2"
        FROM="''${PROFILE_BASE}-$1-link"
        TO="''${PROFILE_BASE}-$2-link"
        ;;
      *)
        echo "Usage:"
        echo "  diff-gen          (Running vs Boot)"
        echo "  diff-gen 198      (Running vs Gen 198)"
        echo "  diff-gen 198 199  (Gen 198 vs Gen 199)"
        exit 1
        ;;
    esac

    # Validation
    if [ ! -e "$FROM" ]; then echo "Error: Source path $FROM not found."; exit 1; fi
    if [ ! -e "$TO" ]; then echo "Error: Target path $TO not found."; exit 1; fi

    ${nvd}/bin/nvd diff "$FROM" "$TO"
  '';
}
