# macbook-pro-nixvm

`macbook-pro-nixvm` is an aarch64 NixOS GNOME workstation running through UTM's
QEMU backend. Nix owns the guest configuration and disk layout; UTM owns its
local `.utm` bundle.

Follow this end to end to recreate the guest from nothing: delete the old `.utm`
bundle, then work through each section in order.

## Create the UTM VM

Download a current NixOS aarch64 minimal installer ISO. In UTM, create a QEMU
Linux ARM64 VM with Hypervisor acceleration, then set:

- 8 CPU cores and 16 GiB memory;
- CPU model to Host and the balloon device enabled;
- a 128 GiB sparse VirtIO disk (the guest sees it as `/dev/vda`);
- the installer ISO as a removable CD/DVD drive;
- VirtIO network in bridged mode, initially using UTM's Automatic interface;
- the `virtio-gpu-gl-pci` display card with SPICE and the QEMU Guest Agent enabled; and
- VirtIO Sound (`virtio-sound-pci`); and
- two VirtFS shares — `/private/etc/nix-darwin` under the tag `share`, and the
  host directory used for file exchange under the tag `vm-shared`.

The share tags must match the `device` values in
`hosts/macbook-pro-nixvm/virtfs.nix`; the guest mounts them at `/etc/nixos`
(read-only) and `/mnt/vm-shared` (read-write).

Leave TSO disabled. It accelerates x86 emulation inside an Apple Silicon guest,
which this native aarch64 guest does not use.

Enable Auto Resolution and leave Retina Mode disabled. The SPICE agent lets
GNOME track the VM window size, while macOS performs HiDPI scaling efficiently.

Enable USB sharing with a limit of two devices. Eject the USB SSD in macOS
before attaching it from UTM's USB toolbar, then detach it in UTM before
mounting it again on macOS.

The bridged network gives the VM its own DHCP lease on the LAN. If the Wi-Fi
access point rejects an additional MAC address, switch this VM to shared/NAT
networking and use the UTM console for access until the LAN issue is resolved.

The guest configuration enables both agents. The QEMU guest agent exposes
management functions such as time synchronization to UTM; the SPICE agent
provides clipboard sharing and dynamic display resolution for the QEMU display.

## Initial installation

In the installer, mount the VirtFS share, partition the new VirtIO disk, create
the target mount point, and install the configuration:

```sh
sudo mkdir -p /run/nixos-flake
sudo mount -t 9p -o trans=virtio,ro share /run/nixos-flake
sudo nix --extra-experimental-features 'nix-command flakes' \
  run github:nix-community/disko -- --mode destroy,format,mount --flake 'path:/run/nixos-flake#macbook-pro-nixvm'
sudo mkdir -p /mnt/etc/nixos
sudo nixos-install --flake 'path:/run/nixos-flake#macbook-pro-nixvm'
```

Remove the installer ISO and boot the disk.

Use the UTM console or the DHCP-assigned address to log in. Existing Patrick
SSH public keys allow key-based SSH access immediately.

## Re-key the password secret

Every fresh VM generates its own SSH host key, so the declared password secret
has to be re-keyed to it before the first password login. On the guest:

```sh
sudo cat /etc/ssh/ssh_host_ed25519_key.pub
```

Set that value as `secrets.hostPubkey` in
`modules/flake-parts/macbook-pro-nixvm.nix`, then re-key from a configured
Patrick administrator machine:

```sh
nix run .#agenix-rekey -- rekey
```

Rebuild on the guest to pick up the re-keyed secret:

```sh
nh os switch /etc/nixos
```

The VM receives only `patrick-password-hash`; the AWS CLI secret has no ACL
for this host.

## Updating the guest

From the guest checkout, pull the intended flake revision and run:

```sh
nh os switch /etc/nixos
```

Both VirtFS mounts are on-demand and non-fatal when UTM does not expose the
share; `/etc/nixos` is read-only and `/mnt/vm-shared` is read-write. Edit and
commit the flake on macOS. The guest builds natively inside the aarch64 VM; its
Btrfs layout, local snapshots, and monthly scrub are declared through nstdl's
standard storage profile.
