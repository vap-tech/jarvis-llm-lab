# Archsrv Notes

## Model Status Indicator

Current model-loading indicator behavior is considered OK and should be preserved:

- green: model is ready and `/api/v1/models` responds successfully
- solid yellow: model is loading locally into RAM/VRAM
- blinking yellow: model is downloading over the network via Hugging Face cache
- red: model is unavailable

Observed behavior is correct in practice:

- switching to a cached model shows solid yellow briefly during local load
- switching to a model that still needs downloading transitions to blinking yellow
