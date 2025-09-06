{{- define "june-tts.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "june-tts.fullname" -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- printf "june-tts-june-tts" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "june-tts.labels" -}}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
app.kubernetes.io/name: {{ include "june-tts.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "june-tts.selectorLabels" -}}
app.kubernetes.io/name: {{ include "june-tts.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "june-tts.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{ include "june-tts.fullname" . }}
{{- else -}}
default
{{- end -}}
{{- end -}}
