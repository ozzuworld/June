{{- define "june-stt.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "june-stt.fullname" -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- printf "june-stt-june-stt" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "june-stt.labels" -}}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
app.kubernetes.io/name: {{ include "june-stt.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "june-stt.selectorLabels" -}}
app.kubernetes.io/name: {{ include "june-stt.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "june-stt.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{ include "june-stt.fullname" . }}
{{- else -}}
default
{{- end -}}
{{- end -}}
