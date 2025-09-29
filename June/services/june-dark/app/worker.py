from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import cv2
import numpy as np
import torch
import asyncio
import logging
from datetime import datetime
import uuid

from models.yolo_detector import YOLODetector
from models.opencti_client import OpenCTIClient
from services.vision_service import VisionService
from services.opencti_service import OpenCTIService
from config.settings import Settings
from utils.gpu_utils import GPUManager
from utils.queue_manager import QueueManager

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="June Dark OSINT Framework",
    description="Advanced OSINT framework with YOLOv11 and OpenCTI integration",
    version="2.0.0"
)

# Global variables
settings = Settings()
gpu_manager = GPUManager()
queue_manager = QueueManager()
yolo_detector: Optional[YOLODetector] = None
vision_service: Optional[VisionService] = None
opencti_client: Optional[OpenCTIClient] = None
opencti_service: Optional[OpenCTIService] = None

# Pydantic models
class DetectionResult(BaseModel):
    id: str
    class_id: int
    class_name: str
    confidence: float
    bbox: List[float]
    center: List[float]
    timestamp: datetime

class OSINTAnalysis(BaseModel):
    image_id: str
    detections: List[DetectionResult]
    opencti_indicators: List[Dict[str, Any]]
    threat_level: str
    metadata: Dict[str, Any]

@app.on_event("startup")
async def startup_event():
    """Initialize all services on startup"""
    global yolo_detector, vision_service, opencti_client, opencti_service
    
    logger.info("Initializing June Dark OSINT Framework...")
    
    try:
        # Initialize GPU manager
        gpu_manager.initialize()
        
        # Initialize YOLO detector with YOLOv11
        yolo_detector = YOLODetector(
            model_size=settings.YOLO_MODEL_SIZE,
            confidence_threshold=settings.YOLO_CONFIDENCE,
            device=0 if torch.cuda.is_available() else 'cpu'
        )
        await yolo_detector.load_model()
        
        # Initialize OpenCTI client
        if settings.OPENCTI_URL and settings.OPENCTI_TOKEN:
            opencti_client = OpenCTIClient(
                url=settings.OPENCTI_URL,
                token=settings.OPENCTI_TOKEN
            )
            await opencti_client.connect()
            
            # Initialize OpenCTI service
            opencti_service = OpenCTIService(opencti_client)
        else:
            logger.warning("OpenCTI not configured - intelligence enrichment disabled")
        
        # Initialize vision service
        vision_service = VisionService(yolo_detector, opencti_service)
        
        # Initialize queue manager
        await queue_manager.initialize(settings.REDIS_URL, settings.RABBIT_URL)
        
        logger.info("June Dark OSINT Framework initialized successfully")
        
    except Exception as e:
        logger.error(f"Failed to initialize services: {str(e)}")
        raise

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    logger.info("Shutting down June Dark OSINT Framework...")
    
    if opencti_client:
        await opencti_client.disconnect()
    
    if queue_manager:
        await queue_manager.close()
    
    gpu_manager.cleanup()

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    gpu_available = torch.cuda.is_available()
    gpu_name = torch.cuda.get_device_name(0) if gpu_available else None
    
    status = {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "services": {
            "yolo": yolo_detector is not None,
            "opencti": opencti_client is not None and await opencti_client.is_connected(),
            "gpu": gpu_available,
            "gpu_name": gpu_name,
            "queue_manager": queue_manager.is_connected()
        },
        "model": "YOLOv11",
        "version": "2.0.0"
    }
    
    return status

@app.post("/detect/objects", response_model=OSINTAnalysis)
async def detect_objects(file: UploadFile = File(...)):
    """Enhanced object detection with YOLOv11 and OpenCTI enrichment"""
    if not yolo_detector:
        raise HTTPException(status_code=503, detail="YOLO detector not initialized")
    
    try:
        # Read and decode image
        contents = await file.read()
        nparr = np.frombuffer(contents, np.uint8)
        image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if image is None:
            raise HTTPException(status_code=400, detail="Invalid image format")
        
        # Generate unique analysis ID
        analysis_id = str(uuid.uuid4())
        
        # Perform YOLO detection
        detections = await yolo_detector.detect(image)
        
        # Convert to structured format
        detection_results = []
        for det in detections:
            detection_result = DetectionResult(
                id=str(uuid.uuid4()),
                class_id=det['class_id'],
                class_name=det['class_name'],
                confidence=det['confidence'],
                bbox=det['bbox'],
                center=det['center'],
                timestamp=datetime.now()
            )
            detection_results.append(detection_result)
        
        # OpenCTI enrichment
        opencti_indicators = []
        threat_level = "unknown"
        
        if opencti_service:
            try:
                # Analyze detections for threat intelligence
                threat_analysis = await opencti_service.analyze_detections(detection_results)
                opencti_indicators = threat_analysis.get('indicators', [])
                threat_level = threat_analysis.get('threat_level', 'low')
                
                # Create indicators in OpenCTI for suspicious objects
                for detection in detection_results:
                    if detection.confidence > 0.8:  # High confidence detections
                        await opencti_service.create_indicator_from_detection(
                            detection, file.filename, analysis_id
                        )
                        
            except Exception as e:
                logger.error(f"OpenCTI enrichment failed: {str(e)}")
        
        # Create analysis result
        analysis = OSINTAnalysis(
            image_id=analysis_id,
            detections=detection_results,
            opencti_indicators=opencti_indicators,
            threat_level=threat_level,
            metadata={
                "filename": file.filename,
                "image_size": image.shape[:2],
                "detection_count": len(detection_results),
                "model": "YOLOv11",
                "processed_at": datetime.now().isoformat()
            }
        )
        
        return analysis
        
    except Exception as e:
        logger.error(f"Detection failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Detection failed: {str(e)}")

@app.post("/detect/batch")
async def batch_detection(
    files: List[UploadFile] = File(...),
    background_tasks: BackgroundTasks = None
):
    """Optimized batch processing for OSINT workflows"""
    if not yolo_detector:
        raise HTTPException(status_code=503, detail="YOLO detector not initialized")
    
    if len(files) > 20:  # Limit batch size
        raise HTTPException(status_code=400, detail="Batch size limited to 20 images")
    
    batch_id = str(uuid.uuid4())
    results = []
    
    try:
        # Load all images
        images = []
        filenames = []
        
        for file in files:
            contents = await file.read()
            nparr = np.frombuffer(contents, np.uint8)
            image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            
            if image is not None:
                images.append(image)
                filenames.append(file.filename)
        
        # Batch inference for better GPU utilization
        batch_detections = await yolo_detector.detect_batch(images)
        
        # Process results
        for idx, detections in enumerate(batch_detections):
            detection_results = []
            
            for det in detections:
                detection_result = DetectionResult(
                    id=str(uuid.uuid4()),
                    class_id=det['class_id'],
                    class_name=det['class_name'],
                    confidence=det['confidence'],
                    bbox=det['bbox'],
                    center=det['center'],
                    timestamp=datetime.now()
                )
                detection_results.append(detection_result)
            
            # Basic threat assessment
            threat_level = "low"
            high_confidence_count = sum(1 for d in detection_results if d.confidence > 0.8)
            if high_confidence_count > 3:
                threat_level = "medium"
            if high_confidence_count > 6:
                threat_level = "high"
            
            analysis = {
                "filename": filenames[idx],
                "detections": [d.dict() for d in detection_results],
                "threat_level": threat_level,
                "detection_count": len(detection_results)
            }
            results.append(analysis)
        
        # Queue for background OpenCTI processing if needed
        if opencti_service and background_tasks:
            background_tasks.add_task(
                process_batch_opencti_enrichment,
                batch_id, results
            )
        
        return {
            "batch_id": batch_id,
            "processed_count": len(results),
            "results": results,
            "model": "YOLOv11",
            "opencti_enrichment": "queued" if opencti_service else "disabled"
        }
        
    except Exception as e:
        logger.error(f"Batch detection failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Batch detection failed: {str(e)}")

@app.post("/opencti/indicators")
async def create_opencti_indicators(indicators_data: Dict[str, Any]):
    """Create threat intelligence indicators in OpenCTI"""
    if not opencti_service:
        raise HTTPException(status_code=503, detail="OpenCTI service not available")
    
    try:
        results = await opencti_service.create_indicators(indicators_data)
        return {"status": "success", "indicators_created": results}
    except Exception as e:
        logger.error(f"Failed to create OpenCTI indicators: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/opencti/search")
async def search_opencti_indicators(
    query: str,
    limit: int = 10,
    indicator_types: Optional[List[str]] = None
):
    """Search OpenCTI indicators"""
    if not opencti_service:
        raise HTTPException(status_code=503, detail="OpenCTI service not available")
    
    try:
        results = await opencti_service.search_indicators(
            query=query,
            limit=limit,
            indicator_types=indicator_types
        )
        return results
    except Exception as e:
        logger.error(f"OpenCTI search failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/gpu/status")
async def gpu_status():
    """Get GPU status and utilization"""
    return gpu_manager.get_status()

@app.get("/queue/status")
async def queue_status():
    """Get queue status and metrics"""
    return await queue_manager.get_status()

async def process_batch_opencti_enrichment(batch_id: str, results: List[Dict]):
    """Background task for OpenCTI enrichment"""
    if not opencti_service:
        return
    
    logger.info(f"Processing OpenCTI enrichment for batch {batch_id}")
    
    try:
        for result in results:
            # Create indicators for high-confidence detections
            high_conf_detections = [
                d for d in result['detections'] 
                if d['confidence'] > 0.8
            ]
            
            if high_conf_detections:
                await opencti_service.create_batch_indicators(
                    batch_id, result['filename'], high_conf_detections
                )
        
        logger.info(f"Completed OpenCTI enrichment for batch {batch_id}")
    except Exception as e:
        logger.error(f"Background OpenCTI enrichment failed for batch {batch_id}: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9009)