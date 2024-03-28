# rubintv

Real-time display front end

## Source Code

* <https://github.com/lsst-ts/rubintv>

## Values

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| frontend.affinity | object | `{}` | Affinity rules for the rubintv frontend pod |
| frontend.debug | bool | `false` | If set to true, enable more verbose logging. |
| frontend.image | object | `{"pullPolicy":"IfNotPresent","repository":"ghcr.io/lsst-ts/rubintv","tag":""}` | Settings for rubintv OCI image |
| frontend.image.pullPolicy | string | `"IfNotPresent"` | Pull policy for the rubintv image |
| frontend.image.repository | string | `"ghcr.io/lsst-ts/rubintv"` | rubintv frontend image to use |
| frontend.image.tag | string | The appVersion of the chart | Tag of rubintv image to use |
| frontend.nodeSelector | object | `{}` | Node selector rules for the rubintv frontend pod |
| frontend.pathPrefix | string | `"/rubintv"` | Prefix for rubintv's frontend API routes. |
| frontend.podAnnotations | object | `{}` | Annotations for the rubintv frontend pod |
| frontend.resources | object | `{}` | Resource limits and requests for the rubintv frontend pod |
| frontend.tolerations | list | `[]` | Tolerations for the rubintv frontend pod |
| fullnameOverride | string | `""` | Override the full name for resources (includes the release name) |
| global.baseUrl | string | Set by Argo CD | Base URL for the environment |
| global.host | string | Set by Argo CD | Host name for ingress |
| global.tsVaultSecretsPath | string | `""` | Relative path for tsVault secrets |
| global.vaultSecretsPath | string | Set by Argo CD | Base path for Vault secrets |
| imagePullSecrets | list | See `values.yaml` | Image pull secrets. |
| ingress.annotations | object | `{}` | Additional annotations to add to the ingress |
| nameOverride | string | `""` | Override the base name for resources |
| redis.affinity | object | `{}` | Affinity rules for the Redis pod |
| redis.config.secretKey | string | `"redis-password"` | Key inside secret from which to get the Redis password (do not change) |
| redis.config.secretName | string | `"rubintv-secrets"` | Name of secret containing Redis password (may require changing if fullnameOverride is set) |
| redis.nodeSelector | object | `{}` | Node selection rules for the Redis pod |
| redis.persistence.accessMode | string | `"ReadWriteOnce"` | Access mode of storage to request |
| redis.persistence.enabled | bool | `true` | Whether to persist Redis storage and thus tokens. Setting this to false will use `emptyDir` and reset all tokens on every restart. Only use this for a test deployment. |
| redis.persistence.size | string | `"1Gi"` | Amount of persistent storage to request |
| redis.persistence.storageClass | string | `""` | Class of storage to request |
| redis.persistence.volumeClaimName | string | `""` | Use an existing PVC, not dynamic provisioning. If this is set, the size, storageClass, and accessMode settings are ignored. |
| redis.podAnnotations | object | `{}` | Pod annotations for the Redis pod |
| redis.resources | object | See `values.yaml` | Resource limits and requests for the Redis pod |
| redis.tolerations | list | `[]` | Tolerations for the Redis pod |
