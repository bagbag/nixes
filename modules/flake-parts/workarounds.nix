{ inputs, ... }:
let
  # Remove once Node 26.7.0 is substituted for aarch64-darwin again.
  cachedNodejsOverlay = final: _: {
    nodejs_26 = inputs.nixpkgs-nodejs.legacyPackages.${final.stdenv.hostPlatform.system}.nodejs_26;
  };
in
{
  nstdl.hosts = {
    nixstation.extraModules = [ { nixpkgs.overlays = [ cachedNodejsOverlay ]; } ];
    nixmobil.extraModules = [ { nixpkgs.overlays = [ cachedNodejsOverlay ]; } ];
    nixbook-air.extraModules = [ { nixpkgs.overlays = [ cachedNodejsOverlay ]; } ];
    macbook-pro.extraModules = [ { nixpkgs.overlays = [ cachedNodejsOverlay ]; } ];
  };
}
