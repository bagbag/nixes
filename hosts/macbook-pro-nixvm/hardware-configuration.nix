{ lib, modulesPath, ... }:
{
  imports = [ (modulesPath + "/profiles/qemu-guest.nix") ];

  boot.initrd.availableKernelModules = [
    "virtio_pci"
    "virtio_blk"
    "virtio_scsi"
    "virtio_net"
  ];

  services.spice-vdagentd.enable = true;

  nixpkgs.hostPlatform = lib.mkDefault "aarch64-linux";
}
