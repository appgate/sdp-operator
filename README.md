# SDP Operator
SDP Operator is a cloud-native project to declaratively configure an Appgate SDP system. 

SDP Operator supports the following API versions:
* v14 (Appgate version 5.3)
* v15 (Appgate version 5.4)
* v16 (Appgate version 5.5)
* v17 (Appgate version 6.0)

SDP Operator supports the following entities:
```
AdminMfaSettings     AdministrativeRole   Appliance             ApplianceCustomization
ClientConnection     Condition            CriteriaScripts       DeviceScript   
Entitlment           EntitlementScript    GlobalSettings        IdentityProvider
IpPool               LocalUser            MfaProvider           Policy
RingfenceRule        ServiceUser          Site                  TrustedCertificate
```

## Requirements
The following tools are required to install the SDP Operator
* helm v3.7.0+ - https://helm.sh/docs/intro/install/
* kubectl - https://kubernetes.io/docs/tasks/tools/#kubectl

## Getting Started
1. Install the SDP Operator CRD charts with Helm. 
   ```shell
   $ helm install sdp-operator-crd oci://ghcr.io/appgate/charts/sdp-operator-crd --version <version> --set version=<api-version>
   ``` 
   where:
   * `api-version` is the API version of the Appgate SDP system (`v14`, `v15`, `v16`, `v17`). This must match the API version of the system you want to configure.
   * `version` is the chart version of the SDP Operator. Browse the available versions in the [Appgate Operator GitHub Container Registry](https://github.com/orgs/appgate/packages?repo_name=sdp-operator). This must match the SDP Operator chart version in step 3.


2. Create a secret containing the username and password for the operator.
   ```shell
   $ kubectl create secret sdp-operator-secret-sdp-operator \
       --from-literal=appgate-operator-user=<user> \
       --from-literal-appgate-operator-password=<password> --namespace sdp-operator
   ``` 
   where
   * `user` and `password` is the credentials that has admin access to the Appgate SDP system.


3. Install the SDP Operator with Helm. Browse the [Parameters](#parameters) for configurable values.
   ```shell
   $ helm install sdp-operator oci://ghcr.io/appgate/charts/sdp-operator --version <version> \
       --set sdp.operator.version=<api-version> \
       --set sdp.operator.host=<host> \
       --set sdp.operator.deviceId=<device-id>
   ```
   where
   * `version` is the chart version of the SDP Operator. Browse the available version in the [Appgate Operator GitHub Container Registry](https://github.com/orgs/appgate/packages?repo_name=sdp-operator). This must match the SDP Operator CRD chart version in step 1.  
   * `api-version` is the API version of the Appgate SDP system (`v14`, `v15`, `v16`, `v17`). This must match the API version of the system you want to configure.
   * `host` is the hostname of the Appgate SDP system you want to configure.
   * `device-id` is the UUID to assign to this operator


## Parameters

### SDP Required Parameters

| Name                    | Description                             | Value |
| ----------------------- | --------------------------------------- | ----- |
| `sdp.operator.host`     | SDP Operator controller host            | `""`  |
| `sdp.operator.deviceId` | SDP Operator device id (uuid v4 format) | `""`  |
| `sdp.operator.version`  | SDP Operator API version                | `v17` |


### SDP Optional Parameters

| Name                             | Description                     | Value                          |
| -------------------------------- | ------------------------------- | ------------------------------ |
| `sdp.operator.image.tag`         | SDP Operator image tag          | `""`                           |
| `sdp.operator.image.pullPolicy`  | SDP Operator pull policy        | `Always`                       |
| `sdp.operator.image.repository`  | SDP operator image registry     | `ghcr.io/appgate/sdp-operator` |
| `sdp.operator.image.pullSecrets` | SDP operator pull secret        | `[]`                           |
| `sdp.operator.logLevel`          | SDP Operator log level          | `info`                         |
| `sdp.operator.timeout`           | SDP Operator event loop timeout | `30`                           |
| `sdp.operator.builtinTags`       | SDP Operator builtin tags       | `builtin`                      |
| `sdp.operator.dryRun`            | SDP Operator dry-run mode       | `true`                         |
| `sdp.operator.cleanup`           | SDP Operator cleanup mode       | `false`                        |
| `sdp.operator.twoWaySync`        | SDP Operator two-way-sync mode  | `true`                         |
| `sdp.operator.sslNoVerify`       | SDP Operator ssl-no-verify mode | `false`                        |
| `sdp.operator.targetTags`        | SDP Operator target tags        | `""`                           |
| `sdp.operator.excludeTags`       | SDP Operator exclude tags       | `""`                           |
| `sdp.operator.caCert`            | SDP Operator host CA cert       | `""`                           |
| `sdp.operator.fernetKey`         | SDP Operator Fernet Key         | `""`                           |
| `sdp.operator.configMapMt`       | SDP Operator metadata configmap | `""`                           |


### Kubernetes parameters

| Name                    | Description                                          | Value  |
| ----------------------- | ---------------------------------------------------- | ------ |
| `serviceAccount.create` | Enable the creation of a ServiceAccount for SDP pods | `true` |
| `rbac.create`           | Whether to create & use RBAC resources or not        | `true` |


This table above was generated using readme-generator-for-helm


## How It Works
Appgate entities are defined in terms of [[https://kubernetes.io/docs/concepts/extend-kubernetes/api-extension/custom-resources/][CRD]] in the k8s cluster so they can be
managed (created, deleted or modified) using `kubectl` command with yaml files
representing those CRD.

The appgate-operator, when running, will listen for changes on those CRD entities,
note that the operator listen to events inside a namespace.

When the operator starts, it gets the actual state from the appgate controller
and from there it starts listening for events.

On each event received it restores a timer, once the timer timeouts (meaning
that no more events were received in that specified time frame) the operator
will proceed to compute and apply a new `Plan`.

A `Plan` is the difference between the current state and the desired state and
it defines for each entity 4 subset of operations to perform:

 - create :: a new entity needs to be created
 - delete :: an existing entity needs to be deleted
 - modify :: an existing entity needs to be modified
 - share :: an entity that won't change

All the entities are identified by name, that way we don't need to save real
uuids in the configuration. Entities referencing other entities (entitlements
reference conditions for instance) do it by name also, the operator resolves
those names into real uuids before doing the queries.

### Errors
There are different sources of errors.

Some entities reference another ones like `entitlements` using `conditions`. If
one entity references another entity that is not in the expected state after the
`Plan` is applied then it's marked as a conflict error. If a plan contains
errors it won't be applied.

Another kind of error is when applying the plan for real. If the REST call to
the operator fails, that entity is marked as failed as well. Then later when
creating the new state this entity that failed will be removed from the new
state (or added if the operation was `delete`).

### Modes of operation
#### DRY_MODE
When this flag is on the operator will compute the plan to apply but it won't do
any call.

#### CLEANUP_ON_STARTUP
When this flag is on the operator when initializing the state for first time
will remove all the entities that are not part of the set of builtin tags (see
[[*Configuration][configuration section]] to know how to configure this set).

#####  Example 1
We have an Appgate system with a condition but we do not have any condition
defined in kubernetes.

```
2020-07-17 17:14:38,940 [INFO] [policies/appgate-test-1] Loop for policies/appgate-test-1 started
2020-07-17 17:14:38,942 [INFO] [entitlements/appgate-test-1] Loop for entitlements/appgate-test-1 started
2020-07-17 17:14:38,943 [INFO] [conditions/appgate-test-1] Loop for conditions/appgate-test-1 started
2020-07-17 17:14:38,945 [INFO] [appgate-operator/appgate-test-1] Getting current state from controller
2020-07-17 17:14:39,228 [INFO] [appgate-operator/appgate-test-1] Ready to get new events and compute a new plan
2020-07-17 17:14:44,235 [INFO] [appgate-operator/appgate-test-1] No more events for a while, creating a plan
2020-07-17 17:14:44,235 [WARNING] [appgate-operator/appgate-test-1] Running in dry-mode, nothing will be created
2020-07-17 17:14:44,236 [INFO] [appgate-operator/appgate-test-1] AppgatePlan Summary:
2020-07-17 17:14:44,236 [INFO] [appgate-operator/appgate-test-1] = <class 'appgate.types.Condition'> Always [ee7b7e6f-e904-4b4f-a5ec-b3bef040643e]
2020-07-17 17:14:44,236 [INFO] [appgate-operator/appgate-test-1] = <class 'appgate.types.Condition'> my-new-condition [1bd1f4a8-d2ca-409d-b925-3530447caf45]
2020-07-17 17:14:44,236 [INFO] [appgate-operator/appgate-test-1] = <class 'appgate.types.Policy'> Builtin Administrator Policy [172143a0-7ed4-11e4-b4a9-0800200c9a66]
2020-07-17 17:14:49,242 [INFO] [appgate-operator/appgate-test-1] No more events for a while, creating a plan
2020-07-17 17:14:49,243 [WARNING] [appgate-operator/appgate-test-1] Running in dry-mode, nothing will be created
2020-07-17 17:14:49,243 [INFO] [appgate-operator/appgate-test-1] AppgatePlan Summary:
2020-07-17 17:14:49,244 [INFO] [appgate-operator/appgate-test-1] = <class 'appgate.types.Condition'> Always [ee7b7e6f-e904-4b4f-a5ec-b3bef040643e]
2020-07-17 17:14:49,244 [INFO] [appgate-operator/appgate-test-1] = <class 'appgate.types.Condition'> my-new-condition [1bd1f4a8-d2ca-409d-b925-3530447caf45]
2020-07-17 17:14:49,244 [INFO] [appgate-operator/appgate-test-1] = <class 'appgate.types.Policy'> Builtin Administrator Policy [172143a0-7ed4-11e4-b4a9-0800200c9a66]
```

As we can see in this example the new condition (not built-in) is detected when
discovering the first state. Because we did not choose to cleanup on startup,
the condition is kept there and not managed by the operator.

##### Example 2
Same example when cleanup is on.

```
2020-07-17 17:20:12,999 [INFO] [policies/appgate-test-1] Loop for policies/appgate-test-1 started
2020-07-17 17:20:13,001 [INFO] [entitlements/appgate-test-1] Loop for entitlements/appgate-test-1 started
2020-07-17 17:20:13,002 [INFO] [conditions/appgate-test-1] Loop for conditions/appgate-test-1 started
2020-07-17 17:20:13,005 [INFO] [appgate-operator/appgate-test-1] Getting current state from controller
2020-07-17 17:20:13,412 [INFO] [appgate-operator/appgate-test-1] Ready to get new events and compute a new plan
2020-07-17 17:20:18,419 [INFO] [appgate-operator/appgate-test-1] No more events for a while, creating a plan
2020-07-17 17:20:18,419 [WARNING] [appgate-operator/appgate-test-1] Running in dry-mode, nothing will be created
2020-07-17 17:20:18,419 [INFO] [appgate-operator/appgate-test-1] AppgatePlan Summary:
2020-07-17 17:20:18,420 [INFO] [appgate-operator/appgate-test-1] - <class 'appgate.types.Condition'> my-new-condition [1bd1f4a8-d2ca-409d-b925-3530447caf45]
2020-07-17 17:20:18,420 [INFO] [appgate-operator/appgate-test-1] = <class 'appgate.types.Condition'> Always [ee7b7e6f-e904-4b4f-a5ec-b3bef040643e]
2020-07-17 17:20:18,420 [INFO] [appgate-operator/appgate-test-1] = <class 'appgate.types.Policy'> Builtin Administrator Policy [172143a0-7ed4-11e4-b4a9-0800200c9a66]
```

Now we can see that the condition was marked as a deletion because it's not defined in the cluster.

If we have the cleanup option on BUT the cluster knows about those entities they are not deleted:

```
  2020-07-17 17:22:38,393 [INFO] [policies/appgate-test-1] Loop for policies/appgate-test-1 started
  2020-07-17 17:22:38,396 [INFO] [entitlements/appgate-test-1] Loop for entitlements/appgate-test-1 started
  2020-07-17 17:22:38,398 [INFO] [conditions/appgate-test-1] Loop for conditions/appgate-test-1 started
  2020-07-17 17:22:38,403 [INFO] [appgate-operator/appgate-test-1] Getting current state from controller
  2020-07-17 17:22:38,707 [INFO] [appgate-operator/appgate-test-1] Ready to get new events and compute a new plan
  2020-07-17 17:22:39,020 [INFO] [appgate-operator/appgate-test-1}] Event op: ADDED <class 'appgate.types.Condition'> with name my-new-condition
  2020-07-17 17:22:44,025 [INFO] [appgate-operator/appgate-test-1] No more events for a while, creating a plan
  2020-07-17 17:22:44,025 [WARNING] [appgate-operator/appgate-test-1] Running in dry-mode, nothing will be created
  2020-07-17 17:22:44,026 [INFO] [appgate-operator/appgate-test-1] AppgatePlan Summary:
  2020-07-17 17:22:44,026 [INFO] [appgate-operator/appgate-test-1] = <class 'appgate.types.Condition'> Always [ee7b7e6f-e904-4b4f-a5ec-b3bef040643e]
  2020-07-17 17:22:44,026 [INFO] [appgate-operator/appgate-test-1] = <class 'appgate.types.Condition'> my-new-condition [1bd1f4a8-d2ca-409d-b925-3530447caf45]
  2020-07-17 17:22:44,027 [INFO] [appgate-operator/appgate-test-1] = <class 'appgate.types.Policy'> Builtin Administrator Policy [172143a0-7ed4-11e4-b4a9-0800200c9a66]
```

#### TWO_WAY_SYNC
This flag makes the appgate-operator to read the current state from the
controller before computing the new plan. Basically whatever entity
created/deleted/modified manually will be reverted.

When it's not set it will just compute the plan against the current state in
memory (which could be different from the one in the controller).

### Secrets
The operator supports 3 ways of dealing with secrets:
 - unencrypted secrets.
 - secrets encrypted with a [[https://cryptography.io/en/latest/fernet/][fernet]] key.
 - secrets saved as =secret= store in k8s.

#### Unencrypted secrets
In the first case (*unencrypted secrets*) we will save the secret in the yaml
file itself (or some tool will add it before pushing the event into k8s). In
this case the operator just uses that value as the value of the secrets field.

#### Encrypted secrets
We can also save an encrypted secret in the yaml file defining the entity, in
this case we need to provide a fermet key value in the environment variable
~APPGATE_OPERATOR_FERNET_KEY~ and the operator will decrypt the contents of the
value before using it.

In order to generate a new fernet key we can run:
```shell
$ python3 -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())'
```

In order to generate a secret with the new key we can do something like this:
```shell
$ SECRET='my-secret'
$ KEY='dFVzzjKCa9mWbeig8dprliGLCXwnwE5Fbycz4Xe2ptk='
$ python3.9 -c 'from cryptography.fernet import Fernet;import os;print(Fernet(os.getenv("KEY")).encrypt(bytes(os.getenv("SECRET").encode())))'
```

Now it's safe to store the secrets in github.

If the variable ~APPGATE_OPERATOR_FERNET_KEY~ is set and the value of the secret
is a string then the operator will use the key to decrypt the secret.

#### k8s secret store
We can also use k8s the secrets store mechanism to save the secrets and reference
them in the yaml file. In this case we just set the value of the field with the
secret to a dictionary like this

```yaml
type: k8s/secret
password: my-secret
```

### bytes
Some fields require bytes as a value (contents from a file for example) encoded
in base64. For now we only support the value encoded as base64 directly in the
yaml file.


## Contributing
### Building SDP Operator
The appgate-operator is provided as a docker image tagged with the appgate API
version. For example:

 - appgate-operator:v14
 - appgate-operator:v15
 - appgate-operator:v16
 - appgate-operator:v17

Each image uses that specific API version by default but contains the specs for
all the API versions supported.

To build the images we use a docker image as a builder with all the dependencies
needed.

In order to create the images run (~make docker-build-image is only needed if we
don't have yet the builder image or if we have changed any dependency):

```shell
make docker-build-image && make docker-images
```

To push the images into a registry just run:
```shell
for tag in v14 v15 v16 v17; do
  docker tag appgate-operator:${tag} user/appgate-operator:${tag} && \
  docker push user/appgate-operator:${tag}
done
```
