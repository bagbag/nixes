{ pkgs, ... }:
{
  # macOS has no native container runtime, so podman runs containers inside a
  # VM ("podman machine") instead of the host kernel directly, unlike the
  # NixOS module (../nixos/podman.nix) which uses Linux containers natively.
  # nix-darwin can't manage that VM's lifecycle, so after `darwin-rebuild
  # switch`, run once: `podman machine init && podman machine start`.
  # The registries/policy config from ../nixos/podman.nix applies inside
  # that VM, not on the host, so it isn't mirrored here.
  environment.systemPackages = with pkgs; [
    podman
    podman-compose
  ];
}
