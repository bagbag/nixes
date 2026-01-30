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
    "d /home/patrick/.config/containers 0755 patrick users -"
    "L+ /home/patrick/.config/containers/policy.json - - - - /etc/containers/policy.json"
    "L+ /home/patrick/.config/containers/registries.conf - - - - /etc/containers/registries.conf"
  ];
}
