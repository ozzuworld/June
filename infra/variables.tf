variable "project_id" {
  type = string
}

variable "region" {
  type    = string
  default = "us-central1"
}

variable "repo_name" {
  type    = string
  default = "apps"
}

variable "orchestrator_image" {
  type = string
}

variable "stt_image" {
  type = string
}

variable "tts_image" {
  type = string
}

variable "firebase_project_id" {
  type = string
}

variable "orch_stream_tts" {
  type    = bool
  default = false
}
