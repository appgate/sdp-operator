# SDP Operator Helm Chart

## Quickstart
```
helm install sdp-operator ghcr.io/appgate/sdp-operator:latest
```

## Parameters
This table below was generated using [readme-generator-for-helm](https://github.com/bitnami-labs/readme-generator-for-helm)

### SDP parameters:

| Name                             | Description                                          | Value                          |
| -------------------------------- | ---------------------------------------------------- | ------------------------------ |
| `sdp.operator.sslNoVerify`       | SDP Operator ssl-no-verify mode                      | `"0"`                          |
| `sdp.operator.twoWaySync`        | SDP Operator two-way-sync mode                       | `"1"`                          |
| `sdp.operator.image.pullSecrets` | SDP operator pull secret                             | `[]`                           |
| `sdp.operator.cofigMapMt`        | SDP Operator metadata configmap                      | `not-defined`                  |
| `sdp.operator.image.pullPolicy`  | SDP Operator pull policy                             | `Always`                       |
| `sdp.operator.builtinTags`       | SDP Operator builtin tags                            | `"builtin"`                    |
| `sdp.operator.caCert`            | SDP Operator host CA cert                            | `not-defined`                  |
| `sdp.operator.dryRun`            | SDP Operator dry-run mode                            | `"1"`                          |
| `sdp.operator.timeout`           | SDP Operator event loop timeout                      | `"30"`                         |
| `sdp.operator.targetTags`        | SDP Operator target tags                             | `""`                           |
| `sdp.operator.version`           | SDP Operator API version                             | `"v16"`                        |
| `sdp.operator.fernetKey`         | SDP Operator Fernet Key                              | `not-defined`                  |
| `sdp.operator.cleanup`           | SDP Operator cleanup mode                            | `"1"`                          |
| `sdp.operator.logLevel`          | SDP Operator log level                               | `info`                         |
| `sdp.operator.image.tag`         | SDP Operator image tag                               | `not-defined`                  |
| `sdp.operator.image.repository`  | SDP operator image registry                          | `ghcr.io/appgate/sdp-operator` |
| `sdp.operator.excludeTags`       | SDP Operator exclude tags                            | `""`                           |

### Kubernetes parameters:

| Name                             | Description                                          | Value                          |
| -------------------------------- | ---------------------------------------------------- | ------------------------------ |
| `serviceAccount.create`          | Enable the creation of a ServiceAccount for SDP pods | `true`                         |
| `rbac.create`                    | Whether to create & use RBAC resources or not        | `true`                         |
