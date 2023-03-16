# Helm Values
Below is the list of Helm values available for configuration.

## Parameters

### Operator Parameters

| Name            | Description                                                                      | Value                             |
| --------------- | -------------------------------------------------------------------------------- | --------------------------------- |
| `sdp.operators` | List of operators to run in the deployment. (Option: sdp-operator, git-operator) | `["sdp-operator","git-operator"]` |


### SDP Operator Parameters

| Name                                | Description                                                                                                                                                                              | Value                          |
| ----------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------ |
| `sdp.sdpOperator.host`              | The hostname of the controller to manage with the operator.                                                                                                                              | `""`                           |
| `sdp.sdpOperator.deviceId`          | The device ID assigned to the operator for authenticating against the controller.                                                                                                        | `""`                           |
| `sdp.sdpOperator.reverseMode`       | Enable the operator in reverse mode (pulls entity from SDP instead of pushing)                                                                                                           | `false`                        |
| `sdp.sdpOperator.oneshotMode`       | Enable the operator in one-shot mode (cannot be combined with reverse-mode)                                                                                                              | `false`                        |
| `sdp.sdpOperator.secret`            | Name of the secret that contains the Admin API credentials used by the operator.                                                                                                         | `""`                           |
| `sdp.sdpOperator.version`           | The API version of the controller.                                                                                                                                                       | `v18`                          |
| `sdp.sdpOperator.logLevel`          | The log level of the operator.                                                                                                                                                           | `info`                         |
| `sdp.sdpOperator.timeout`           | The duration in seconds that the operator will wait for a new event. The operator will compute the plan if the timeout expires. The timer is reset to 0 every time an event if received. | `30`                           |
| `sdp.sdpOperator.builtinTags`       | The list of tags that defines a built-in entity. Built-in entities are never deleted.                                                                                                    | `["builtin"]`                  |
| `sdp.sdpOperator.targetTags`        | The list of tags that define the entities to sync. Tagged entities will be synced.                                                                                                       | `[]`                           |
| `sdp.sdpOperator.excludeTags`       | The list of tags that define the entities to exclude from syncing. Tagged entities will be ignored.                                                                                      | `[]`                           |
| `sdp.sdpOperator.sslNoVerify`       | verify the SSL certificate of the controller.                                                                                                                                            | `false`                        |
| `sdp.sdpOperator.dryRun`            | Run the operator in Dry Run mode. The operator will compute the plan but will not make REST calls to the controller to sync the state.                                                   | `true`                         |
| `sdp.sdpOperator.cleanup`           | Delete entities from the controller to sync the entities on the operator.                                                                                                                | `false`                        |
| `sdp.sdpOperator.twoWaySync`        | Read the current configuration from the controller before computing the plan.                                                                                                            | `true`                         |
| `sdp.sdpOperator.fernetKey`         | The fernet key to use when decrypting secrets in entities.                                                                                                                               | `""`                           |
| `sdp.sdpOperator.caCert`            | The controller's CA Certificate in PEM format. It may be a base64-encoded string or string as-is.                                                                                        | `""`                           |
| `sdp.sdpOperator.image.tag`         | The image tag of the operator.                                                                                                                                                           | `""`                           |
| `sdp.sdpOperator.image.pullPolicy`  | The image pull policy of the operator.                                                                                                                                                   | `Always`                       |
| `sdp.sdpOperator.image.repository`  | The repository to pull the operator image from.                                                                                                                                          | `ghcr.io/appgate/sdp-operator` |
| `sdp.sdpOperator.image.pullSecrets` | The secret to access the repository.                                                                                                                                                     | `[]`                           |


### Git Operator

| Name                                        | Description                                                                                                                                                                              | Value                          |
| ------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------ |
| `sdp.gitOperator.version`                   | The API version of the controller.                                                                                                                                                       | `v18`                          |
| `sdp.gitOperator.logLevel`                  | The log level of the operator.                                                                                                                                                           | `info`                         |
| `sdp.gitOperator.timeout`                   | The duration in seconds that the operator will wait for a new event. The operator will compute the plan if the timeout expires. The timer is reset to 0 every time an event if received. | `30`                           |
| `sdp.gitOperator.targetTags`                | The list of tags that define the entities to sync. Tagged entities will be synced.                                                                                                       | `[]`                           |
| `sdp.gitOperator.dryRun`                    | Run the operator in Dry Run mode. The operator will compute the plan but will not commit/push.                                                                                           | `true`                         |
| `sdp.gitOperator.git.vendor`                | The vendor of the git repository: github, gitlab                                                                                                                                         | `github`                       |
| `sdp.gitOperator.git.mainBranch`            | Main branch of the repository to clone the repository                                                                                                                                    | `""`                           |
| `sdp.gitOperator.git.baseBranch`            | Base branch of the repository to create pull requests                                                                                                                                    | `""`                           |
| `sdp.gitOperator.git.repository`            | The name of the repository (e.g. organization/repository)                                                                                                                                | `""`                           |
| `sdp.gitOperator.secret`                    | Name of the secret that contains the SSH key and token for the git repository                                                                                                            | `""`                           |
| `sdp.gitOperator.git.hostname`              | Hostname of the git repository including the port (if not well-known port)                                                                                                               | `""`                           |
| `sdp.gitOperator.git.sshPort`               | Alternate ssh port for the git repository (if not well-known port)                                                                                                                       | `""`                           |
| `sdp.gitOperator.git.strictHostKeyChecking` | Enable StrictHostKeyChecking when cloning repository via SSH                                                                                                                             | `true`                         |
| `sdp.gitOperator.image.tag`                 | The image tag of the operator.                                                                                                                                                           | `""`                           |
| `sdp.gitOperator.image.pullPolicy`          | The image pull policy of the operator.                                                                                                                                                   | `Always`                       |
| `sdp.gitOperator.image.repository`          | The repository to pull the operator image from.                                                                                                                                          | `ghcr.io/appgate/sdp-operator` |
| `sdp.gitOperator.image.pullSecrets`         | The secret to access the repository.                                                                                                                                                     | `[]`                           |


### External Secret Configuration

| Name                                          | Description                                           | Value   |
| --------------------------------------------- | ----------------------------------------------------- | ------- |
| `sdp.externalSecret.enabled`                  | Enable the loading of secrets from an external source | `false` |
| `sdp.externalSecret.type`                     | Type of the external secret source (Option: vault)    | `""`    |
| `sdp.externalSecret.source.vault.address`     | Hostname of the Vault                                 | `""`    |
| `sdp.externalSecret.source.vault.tokenSecret` | Token to use for authenticating against the Vault     | `""`    |
| `sdp.externalSecret.source.vault.sslNoVerify` | Disables SSL verification on Vault connection         | `false` |


### External File Configuration

| Name                                     | Description                                                    | Value   |
| ---------------------------------------- | -------------------------------------------------------------- | ------- |
| `sdp.externalFile.enabled`               | Enable the loading of files from an external source            | `false` |
| `sdp.externalFile.type`                  | Type of the external file source (Option: http, s3)            | `""`    |
| `sdp.externalFile.source.http.address`   | Hostname of the HTTP file server                               | `""`    |
| `sdp.externalFile.source.s3.address`     | Hostname of the S3 object storage                              | `""`    |
| `sdp.externalFile.source.s3.keySecret`   | Name of the secret that contains the access key and secret key | `""`    |
| `sdp.externalFile.source.s3.sslNoVerify` | Disables SSL verification on S3 connection                     | `false` |


### Kubernetes Parameters

| Name                    | Description                                          | Value  |
| ----------------------- | ---------------------------------------------------- | ------ |
| `serviceAccount.create` | Enable the creation of a ServiceAccount for SDP pods | `true` |
| `rbac.create`           | create & use RBAC resources or not                   | `true` |

