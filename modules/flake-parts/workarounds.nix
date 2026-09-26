{ inputs, ... }:
let
  # Use the separately pinned, cache-verified Node 26 on both Darwin hosts.
  cachedNodejsOverlay = final: _: {
    nodejs_26 = inputs.nixpkgs-nodejs.legacyPackages.${final.stdenv.hostPlatform.system}.nodejs_26;
  };

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
  nstdl.hosts = {
    nixbook-air.extraModules = [ { nixpkgs.overlays = [ cachedNodejsOverlay ]; } ];
    macbook-pro.extraModules = [
      { nixpkgs.overlays = [ cachedNodejsOverlay quiDarwinTmpdirOverlay ]; }
    ];
  };
}
