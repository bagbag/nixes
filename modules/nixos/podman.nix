{
  virtualisation = {
    containers = {
      enable = true;

      policy = {
        default = [ { type = "insecureAcceptAnything"; } ];
      };

      registries = {
        search = [
          "docker.io"
          "quay.io"
        ];
      };
    };

    podman = {
      enable = true;
      defaultNetwork.settings.dns_enabled = true;
    };
  };

  systemd.tmpfiles.rules = [
    "d /home/p0v0/.config/containers 0755 p0v0 users -"
    "L+ /home/p0v0/.config/containers/policy.json - - - - /etc/containers/policy.json"
    "L+ /home/p0v0/.config/containers/registries.conf - - - - /etc/containers/registries.conf"
  ];
}
