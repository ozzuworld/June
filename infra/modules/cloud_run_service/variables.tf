variable "service_name"  { type = string }
variable "region"        { type = string }
variable "image"         { type = string }
variable "args"          { type = list(string) default = [] }
variable "env"           { type = map(string)  default = {} }
variable "cpu"           { type = string       default = "1" }
variable "memory"        { type = string       default = "1Gi" }
variable "port"          { type = number       default = 8080 }
variable "min_instances" { type = number       default = 0 }
variable "max_instances" { type = number       default = 20 }
