{ ... }:
let
  # qui's tests take t.TempDir() from nixpkgs' preCheck TMPDIR=/tmp, which is a
  # symlink to /private/tmp on darwin; qui's partial-pool escape guard leaves the
  # root unresolved and rejects every propagation. Remove once nixpkgs resolves
  # TMPDIR on darwin.
  quiDarwinTmpdirOverlay = _: prev: {
    qui = prev.qui.overrideAttrs (_: {
      preCheck = "export TMPDIR=/private/tmp";
    });
  };
in
{
  nstdl.hosts.macbook-pro.extraModules = [
    { nixpkgs.overlays = [ quiDarwinTmpdirOverlay ]; }
  ];
}
