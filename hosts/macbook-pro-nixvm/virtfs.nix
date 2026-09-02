{
  fileSystems."/etc/nixos" = {
    device = "share";
    fsType = "9p";
    options = [
      "trans=virtio"
      "ro"
      "nofail"
      "x-systemd.automount"
    ];
  };

  fileSystems."/mnt/vm-shared" = {
    device = "vm-shared";
    fsType = "9p";
    options = [
      "trans=virtio"
      "rw"
      "nofail"
      "x-systemd.automount"
    ];
  };
}
