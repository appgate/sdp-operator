# SDP Operator
SDP Operator is a cloud-native project to declaratively configure an Appgate SDP system. 

SDP Operator supports the following API versions:
* v14 (Appgate version 5.3)
* v15 (Appgate version 5.4)
* v16 (Appgate version 5.5)
* v17 (Appgate version 6.0)

## Requirements
The following tools are required to install the SDP Operator
* helm v3.7.0+ - https://helm.sh/docs/intro/install/
* kubectl - https://kubernetes.io/docs/tasks/tools/#kubectl

## Getting Started

Browse the available charts versions in the [SDP Operator GitHub Container Registry](https://github.com/appgate/sdp-operator/pkgs/container/charts%2Fsdp-operator).

1. Install the SDP Operator CRD charts with Helm. 
   ```shell
   $ helm install sdp-operator-crd oci://ghcr.io/appgate/charts/sdp-operator-crd \
      --version <version> \
      --set version=<api-version> \
      --namespace sdp-system
   ```
   * `api-version` : API version of the controller (`v14`, `v15`, `v16`, `v17`).
   * `version` : chart version of the SDP Operator.


2. Create a secret containing the username and password for the operator.
   ```shell
   $ kubectl create secret sdp-operator-secret-sdp-operator \
       --from-literal=appgate-operator-user=<user> \
       --from-literal-appgate-operator-password=<password> \
       --namespace sdp-system
   ``` 
   * `user` : Username of the user with admin access to the controller.
   * `password`: Password of the user with admin access to the controller.


3. Install the SDP Operator with Helm. Browse the options in [values.yaml](#parameters).
   ```shell
   $ helm install sdp-operator oci://ghcr.io/appgate/charts/sdp-operator \ 
       --version <version> \
       --set sdp.operator.version=<api-version> \
       --set sdp.operator.host=<host> \
       --set sdp.operator.deviceId=<device-id> \
       --namespace sdp-system
   ```
   * `version` : chart version of the SDP Operator. Must match the CRD chart version in Step 1.
   * `api-version` : API version of the controller. (`v14`, `v15`, `v16`, `v17`).
   * `host` : Hostname of the controller you want to configure.
   * `device-id` : UUID v4 assigned to this operator.


## Parameters

### SDP Required Parameters

| Name                    | Description                                                                       | Value |
| ----------------------- | --------------------------------------------------------------------------------- | ----- |
| `sdp.operator.host`     | The hostname of the controller to manage with the operator.                       | `""`  |
| `sdp.operator.deviceId` | The device ID assigned to the operator for authenticating against the controller. | `""`  |
| `sdp.operator.version`  | The API version of the controller.                                                | `v17` |


### SDP Optional Parameters

| Name                             | Description                                                                                                                                                                              | Value                          |
| -------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------ |
| `sdp.operator.image.tag`         | The image tag of the operator.                                                                                                                                                           | `""`                           |
| `sdp.operator.image.pullPolicy`  | The image pull policy of the operator.                                                                                                                                                   | `Always`                       |
| `sdp.operator.image.repository`  | The repository to pull the operator image from.                                                                                                                                          | `ghcr.io/appgate/sdp-operator` |
| `sdp.operator.image.pullSecrets` | The secret to access the repository.                                                                                                                                                     | `[]`                           |
| `sdp.operator.logLevel`          | The log level of the operator.                                                                                                                                                           | `info`                         |
| `sdp.operator.timeout`           | The duration in seconds that the operator will wait for a new event. The operator will compute the plan if the timeout expires. The timer is reset to 0 every time an event if received. | `30`                           |
| `sdp.operator.builtinTags`       | The list of tags that defines a built-in entity. Built-in entities are never deleted.                                                                                                    | `["builtin"]`                  |
| `sdp.operator.dryRun`            | Whether to run the operator in Dry Run mode. The operator will compute the plan but will not make REST calls to the controller to sync the state.                                        | `true`                         |
| `sdp.operator.cleanup`           | Whether to delete entities from the controller to sync the entities on the operator.                                                                                                     | `false`                        |
| `sdp.operator.twoWaySync`        | Whether to read the current configuration from the controller before computing the plan.                                                                                                 | `true`                         |
| `sdp.operator.sslNoVerify`       | Whether to verify the SSL certificate of the controller.                                                                                                                                 | `false`                        |
| `sdp.operator.targetTags`        | The list of tags that define the entities to sync. Tagged entities will be synced.                                                                                                       | `[]`                           |
| `sdp.operator.excludeTags`       | The list of tags that define the entities to exclude from syncing. Tagged entities will be ignored.                                                                                      | `[]`                           |
| `sdp.operator.caCert`            | The controller's CA Certificate in PEM format. It may be a base64-encoded string or string as-is.                                                                                        | `""`                           |
| `sdp.operator.fernetKey`         | The fernet key to use when decrypting secrets in entities.                                                                                                                               | `""`                           |
| `sdp.operator.configMapMt`       | The config map to store metadata for entities.                                                                                                                                           | `""`                           |


### Kubernetes parameters

| Name                    | Description                                          | Value  |
| ----------------------- | ---------------------------------------------------- | ------ |
| `serviceAccount.create` | Enable the creation of a ServiceAccount for SDP pods | `true` |
| `rbac.create`           | Whether to create & use RBAC resources or not        | `true` |


This table above was generated using [readme-generator-for-helm](https://github.com/bitnami-labs/readme-generator-for-helm)


## How It Works
[Custom Resource Definitions (CRD)](https://kubernetes.io/docs/tasks/extend-kubernetes/custom-resources/custom-resource-definitions/) on Kubernetes allow the operator to represent Appgate SDP entities as YAMLs. Each instance of an entity is stored as a Custom Resource. The operator reads each instance's spec and syncs the entity with the controller using the Admin API. SDP Operator consumes a version from [Appgate SDP OpenAPI Spec](https://github.com/appgate/sdp-api-specification) to generate entities for a given version of the controller. 

For each entity, the operator begins a timer and an event loop to listen for any changes happening on the cluster. Every time an event is received, the timer resets. After the timeout period has expired (in other words, when no event has newly arrived), the operator proceeds to compute a Plan. A Plan represents the difference between the current state on the controller vs the desired state defined in Kubernetes - it outlines what entities will be created/updated/deleted on the controller. After the plan is computed, the operator to execute the Plan on the controller using the API in order to produce the desired state. 

It is important to note that, by design, any state defined in Kubernetes wins over state in the SDP system - any external changes made outside the operator will be overwritten. For example, if an administrator makes a change to the Policy via admin UI, the operator will determine the change as 'out-of-sync- and undoes the change. 

### Secrets Management
The operator supports 3 ways to handle sensitive information in YAML files:
1. Unencrypted secrets
2. Secrets encrypted with a fernet key
3. Secrets created as a Secret on kubernetes

#### Unencrypted Secrets
Secret is stored as-is in the YAML file. The operator will use that value as the value for the secret field. This is not recommended in production.

#### Secrets Encrypted with a Fernet Key
Sensitive information can be stored in the YAML as encrypted secrets using [fernet (symmetric encryption)](https://cryptography.io/en/latest/fernet/).

To generate a new fernet key, run:
```shell
$ python3 -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())'
```

To generate a secret with the key, run:
```shell
$ export SECRET="super-sensitive-information"
$ export KEY="dFVzzjKCa9mWbeig8dprliGLCXwnwE5Fbycz4Xe2ptk="
$ python3 -c 'from cryptography.fernet import Fernet;import os;print(Fernet(os.getenv("KEY")).encrypt(bytes(os.getenv("SECRET").encode())))'
```

After generating the secret, the value is safe to be stored inside the YAML file. When the operator encounters such field, it will read the value of environment variable `APPGATE_OPERATOR_FERNET_KET` to decrypt and read secrets in entities.

#### Secrets using Kubernetes Secrets
Alternatively, the operator supports reading secrets from Kubernetes. 

Let's say, we created the secret below on the Kubernetes cluster.
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: my-secret
data:
  password: YmFyCg==
```

To instruct the operator to use this secret, specify the value of the entity's field with the following dictionary
```yaml
fieldOne:
  type: "k8s/secret",
  name: "my-secret",
  key: "password"
```

When operator sees an entity field with `type: k8s/secret`, it will read the Kubernetes secret to find the value it can use to decrypt and read the secret.

### CA Certificates
CA certificate in PEM format can be stored in env `APPGATE_OPERATOR_CACERT`. We recommend storing the contents of the PEM as a base64 encoded string. 
``` shell
$ export APPGATE_OPERATOR_CACERT=`cat cert.ca`
```

## Advanced Usage
### Dump Current Entities into YAML
`dump-entities` command will read the entities from an existing SDP system and dump them into YAML.
```shell
$ python3 -m appgate --spec-directory /root/appgate/api_specs/v15 dump-entities
```

The above command will generate a directory that contains the YAML
```shell
$ ls -l example-v15/
total 52
-rw-r--r-- 1 root root 1756 Jul 20 23:03 administrativerole.yaml
-rw-r--r-- 1 root root 3537 Jul 20 23:03 appliance.yaml
-rw-r--r-- 1 root root  143 Jul 20 23:03 clientconnection.yaml
-rw-r--r-- 1 root root  184 Jul 20 23:03 condition.yaml
-rw-r--r-- 1 root root  194 Jul 20 23:03 criteriascripts.yaml
-rw-r--r-- 1 root root  332 Jul 20 23:03 globalsettings.yaml
-rw-r--r-- 1 root root 1405 Jul 20 23:03 identityprovider.yaml
-rw-r--r-- 1 root root  423 Jul 20 23:03 ippool.yaml
-rw-r--r-- 1 root root  251 Jul 20 23:03 localuser.yaml
-rw-r--r-- 1 root root  479 Jul 20 23:03 mfaprovider.yaml
-rw-r--r-- 1 root root 1054 Jul 20 23:03 policy.yaml
-rw-r--r-- 1 root root  695 Jul 20 23:03 ringfencerule.yaml
-rw-r--r-- 1 root root  602 Jul 20 23:03 site.yaml
```

### Validate Entities against an OpenAPI Specification
`validate-entities` command will validate the compatibility of entities against a version of the OpenAPI specification. This is useful for verifying if entities dumped from one SDP system is compatible with another SDP system.

```shell
$ python3 -m appgate --spec-directory /root/appgate/api_specs/v17 validate-entities examples-v15/
```

In the example above, we validated the v15 entities (generated by `dump-entities` command) to a v17 OpenAPI specification. The command will attempt to load all entities defined in `examples-v15-entities/` as a v17 entities, reporting errors if encountered any.


## Development
### Versioning
The versioning of the SDP Operator is managed in [k8s/operator/Chart.yaml](k8s/operator/Chart.yaml)

```
version: 0.1.2
appVersion: "0.1.0"
```
- `.Chart.appVersion` is used as the SDP Operator image tag. See [deployment.yaml line 84](k8s/operator/templates/deployment.yaml)
- `.Chart.version` is used as the SDP Operator and CRD chart version. See [GitHub Action line 85](.github/workflows/docker.yml)

### Cheatsheet
Test changes by mounting local repository and kubeconfig
```
$ docker build . -f docker/Dockerfile -t sdp-operator:dev
$ docker run --rm -it -v $HOME/.kube/:/root/.kube/ -v $PWD:/test/ -w /test  --dns 10.97.2.20 --entrypoint /bin/bash sdp-operator:dev
$ /root/run.sh
```

Test changes on Kubernetes cluster
```
$ docker build . -f docker/Dockerfile -t registry.example.com/sdp-operator:dev
$ docker push registry.example.com/sdp-operator:dev
$ helm upgrade --install sdp-operator k8s/operator \
   --set sdp.operator.image.repository=registry.example.com \
   --set sdp.operator.image.tag=dev \
   --set sdp.operator.version=<version> \
   --set sdp.operator.host=<hostname> \
   --set sdp.operator.deviceId=<deviceId>
```
