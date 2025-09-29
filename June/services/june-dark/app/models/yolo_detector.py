import torch
import cv2
import numpy as np
from ultralytics import YOLO
from typing import List, Dict, Any, Optional, Tuple
import logging
import asyncio
from concurrent.futures import ThreadPoolExecutor
import time

logger = logging.getLogger(__name__)

class YOLODetector:
    """YOLOv11 detector optimized for OSINT applications"""
    
    # YOLOv11 model variants and their characteristics
    MODEL_VARIANTS = {
        'nano': {'model': 'yolo11n.pt', 'size': 'fastest', 'accuracy': 'lowest'},
        'small': {'model': 'yolo11s.pt', 'size': 'fast', 'accuracy': 'good'},
        'medium': {'model': 'yolo11m.pt', 'size': 'balanced', 'accuracy': 'better'},
        'large': {'model': 'yolo11l.pt', 'size': 'slower', 'accuracy': 'high'},
        'extra_large': {'model': 'yolo11x.pt', 'size': 'slowest', 'accuracy': 'highest'}
    }
    
    # High-priority classes for OSINT analysis
    PRIORITY_CLASSES = {
        'person', 'car', 'motorcycle', 'bicycle', 'truck', 'bus',
        'laptop', 'cell phone', 'backpack', 'handbag', 'suitcase',
        'knife', 'scissors', 'stop sign', 'traffic light'
    }
    
    def __init__(
        self,
        model_size: str = 'small',
        confidence_threshold: float = 0.4,
        iou_threshold: float = 0.7,
        device: str = 'auto',
        max_detections: int = 100
    ):
        self.model_size = model_size
        self.confidence_threshold = confidence_threshold
        self.iou_threshold = iou_threshold
        self.max_detections = max_detections
        self.model: Optional[YOLO] = None
        self.device = device
        self.executor = ThreadPoolExecutor(max_workers=2)
        self.model_loaded = False
        
        # Performance metrics
        self.inference_times = []
        self.total_detections = 0
        
        logger.info(f"YOLOv11 Detector initialized with model size: {model_size}")
    
    async def load_model(self) -> None:
        """Load YOLOv11 model asynchronously"""
        try:
            if self.model_size not in self.MODEL_VARIANTS:
                raise ValueError(f"Unsupported model size: {self.model_size}")
            
            model_path = self.MODEL_VARIANTS[self.model_size]['model']
            logger.info(f"Loading YOLOv11 model: {model_path}")
            
            # Load model in executor to avoid blocking
            loop = asyncio.get_event_loop()
            self.model = await loop.run_in_executor(
                self.executor,
                self._load_model_sync,
                model_path
            )
            
            # Configure device
            if self.device == 'auto':
                self.device = 0 if torch.cuda.is_available() else 'cpu'
            
            if torch.cuda.is_available() and isinstance(self.device, int):
                self.model.to(f'cuda:{self.device}')
                logger.info(f"Model loaded on GPU: {torch.cuda.get_device_name(self.device)}")
            else:
                logger.info("Model loaded on CPU")
            
            self.model_loaded = True
            logger.info("YOLOv11 model loaded successfully")
            
        except Exception as e:
            logger.error(f"Failed to load YOLOv11 model: {str(e)}")
            raise
    
    def _load_model_sync(self, model_path: str) -> YOLO:
        """Synchronous model loading"""
        return YOLO(model_path)
    
    async def detect(self, image: np.ndarray) -> List[Dict[str, Any]]:
        """Detect objects in a single image"""
        if not self.model_loaded:
            raise RuntimeError("Model not loaded. Call load_model() first.")
        
        try:
            start_time = time.time()
            
            # Run inference in executor
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(
                self.executor,
                self._detect_sync,
                image
            )
            
            # Process results
            detections = self._process_results(results, image.shape)
            
            # Update metrics
            inference_time = time.time() - start_time
            self.inference_times.append(inference_time)
            self.total_detections += len(detections)
            
            logger.debug(f"Detected {len(detections)} objects in {inference_time:.3f}s")
            return detections
            
        except Exception as e:
            logger.error(f"Detection failed: {str(e)}")
            raise
    
    async def detect_batch(self, images: List[np.ndarray]) -> List[List[Dict[str, Any]]]:
        """Optimized batch detection for multiple images"""
        if not self.model_loaded:
            raise RuntimeError("Model not loaded. Call load_model() first.")
        
        try:
            start_time = time.time()
            
            # Run batch inference in executor
            loop = asyncio.get_event_loop()
            batch_results = await loop.run_in_executor(
                self.executor,
                self._detect_batch_sync,
                images
            )
            
            # Process all results
            all_detections = []
            for i, results in enumerate(batch_results):
                detections = self._process_results(results, images[i].shape)
                all_detections.append(detections)
            
            # Update metrics
            inference_time = time.time() - start_time
            total_detections = sum(len(dets) for dets in all_detections)
            
            logger.info(
                f"Batch processed {len(images)} images with {total_detections} "
                f"total detections in {inference_time:.3f}s"
            )
            
            return all_detections
            
        except Exception as e:
            logger.error(f"Batch detection failed: {str(e)}")
            raise
    
    def _detect_sync(self, image: np.ndarray) -> Any:
        """Synchronous detection for single image"""
        results = self.model.predict(
            image,
            conf=self.confidence_threshold,
            iou=self.iou_threshold,
            imgsz=640,
            verbose=False,
            device=self.device,
            max_det=self.max_detections
        )
        return results[0] if results else None
    
    def _detect_batch_sync(self, images: List[np.ndarray]) -> List[Any]:
        """Synchronous batch detection"""
        results = self.model.predict(
            images,
            conf=self.confidence_threshold,
            iou=self.iou_threshold,
            imgsz=640,
            verbose=False,
            device=self.device,
            max_det=self.max_detections
        )
        return results
    
    def _process_results(
        self, 
        results: Any, 
        image_shape: Tuple[int, int, int]
    ) -> List[Dict[str, Any]]:
        """Process YOLO results into structured format"""
        detections = []
        
        if results is None or results.boxes is None:
            return detections
        
        boxes = results.boxes
        height, width = image_shape[:2]
        
        for i in range(len(boxes)):
            # Extract box data
            box = boxes.xyxy[i].cpu().numpy()
            confidence = float(boxes.conf[i].cpu().numpy())
            class_id = int(boxes.cls[i].cpu().numpy())
            class_name = self.model.names[class_id]
            
            # Calculate center point
            center_x = float((box[0] + box[2]) / 2)
            center_y = float((box[1] + box[3]) / 2)
            
            # Normalize coordinates
            bbox_normalized = [
                float(box[0] / width),   # x1
                float(box[1] / height),  # y1
                float(box[2] / width),   # x2
                float(box[3] / height)   # y2
            ]
            
            center_normalized = [
                float(center_x / width),
                float(center_y / height)
            ]
            
            # Determine priority based on class
            is_priority = class_name.lower() in self.PRIORITY_CLASSES
            
            detection = {
                'class_id': class_id,
                'class_name': class_name,
                'confidence': confidence,
                'bbox': [float(box[0]), float(box[1]), float(box[2]), float(box[3])],
                'bbox_normalized': bbox_normalized,
                'center': [center_x, center_y],
                'center_normalized': center_normalized,
                'area': float((box[2] - box[0]) * (box[3] - box[1])),
                'is_priority': is_priority,
                'image_dimensions': {'width': width, 'height': height}
            }
            
            detections.append(detection)
        
        # Sort by confidence (highest first)
        detections.sort(key=lambda x: x['confidence'], reverse=True)
        
        return detections
    
    def get_performance_stats(self) -> Dict[str, Any]:
        """Get performance statistics"""
        if not self.inference_times:
            return {"status": "no_data"}
        
        avg_time = np.mean(self.inference_times)
        min_time = np.min(self.inference_times)
        max_time = np.max(self.inference_times)
        
        return {
            "model_size": self.model_size,
            "model_path": self.MODEL_VARIANTS[self.model_size]['model'],
            "total_inferences": len(self.inference_times),
            "total_detections": self.total_detections,
            "avg_inference_time": round(avg_time, 4),
            "min_inference_time": round(min_time, 4),
            "max_inference_time": round(max_time, 4),
            "fps_estimate": round(1.0 / avg_time, 2) if avg_time > 0 else 0,
            "device": str(self.device),
            "gpu_available": torch.cuda.is_available(),
            "confidence_threshold": self.confidence_threshold,
            "iou_threshold": self.iou_threshold
        }
    
    def reset_stats(self) -> None:
        """Reset performance statistics"""
        self.inference_times.clear()
        self.total_detections = 0
        logger.info("Performance statistics reset")
    
    def update_thresholds(
        self, 
        confidence: Optional[float] = None,
        iou: Optional[float] = None
    ) -> None:
        """Update detection thresholds dynamically"""
        if confidence is not None:
            self.confidence_threshold = confidence
            logger.info(f"Confidence threshold updated to {confidence}")
        
        if iou is not None:
            self.iou_threshold = iou
            logger.info(f"IoU threshold updated to {iou}")
    
    async def warmup(self, num_runs: int = 3) -> Dict[str, float]:
        """Warm up the model with dummy data"""
        logger.info(f"Warming up YOLOv11 model with {num_runs} runs")
        
        # Create dummy image
        dummy_image = np.random.randint(0, 255, (640, 640, 3), dtype=np.uint8)
        
        warmup_times = []
        for i in range(num_runs):
            start_time = time.time()
            await self.detect(dummy_image)
            warmup_time = time.time() - start_time
            warmup_times.append(warmup_time)
            logger.debug(f"Warmup run {i+1}: {warmup_time:.3f}s")
        
        # Reset stats after warmup
        self.reset_stats()
        
        avg_warmup_time = np.mean(warmup_times)
        logger.info(f"Model warmup completed. Average time: {avg_warmup_time:.3f}s")
        
        return {
            "warmup_runs": num_runs,
            "average_time": avg_warmup_time,
            "times": warmup_times
        }
    
    def __del__(self):
        """Cleanup resources"""
        if hasattr(self, 'executor'):
            self.executor.shutdown(wait=True)