{{/*
Expand the name of the chart.
*/}}
{{- define "sdp-operator.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "sdp-operator.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "sdp-operator.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "sdp-operator.labels" -}}
helm.sh/chart: {{ include "sdp-operator.chart" . }}
{{ include "sdp-operator.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "sdp-operator.selectorLabels" -}}
app.kubernetes.io/name: {{ include "sdp-operator.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
ServiceAccount
*/}}
{{- define "serviceAccountName" }}
{{- $ := index . 0 }}
{{- $var := index . 2 }}
{{- $default := index . 3 }}
{{- if $var }}
{{- $var }}
{{- else }}
{{- with index . 1 }}
{{- include "sdp-operator.fullname" . }}-{{- $default }}
{{- end }}
{{- end -}}
{{- end -}}

{{- define "gitServiceAccountName" }}
{{- include "serviceAccountName" (list $ . .Values.sdp.gitOperator.serviceAccount.name "git") }}
{{- end -}}

{{- define "sdpServiceAccountName" }}
{{- include "serviceAccountName" (list $ . .Values.sdp.sdpOperator.serviceAccount.name "sdp") }}
{{- end -}}

{{/*
Operator Secrets
*/}}
{{- define "sdp-operator.secret" -}}
{{- printf "sdp-operator-%s-secret" .Release.Name }}
{{- end }}

{{/*
Operator Config
*/}}
{{- define "sdp-operator.config" -}}
{{- printf "sdp-operator-config-%s" .Release.Name }}
{{- end }}

{{/*
Operator Metadata Config
*/}}
{{- define "sdp-operator.config-mt" -}}
{{- printf "sdp-operator-config-mt-%s" .Release.Name }}
{{- end }}
