#!/usr/bin/env python3
"""Local-only resumable triage, or explicit catalog projection repair."""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sacc_takeout.library import LibraryDB
from sacc_takeout.triage import repair_catalog, run_triage

VOCAB = ["sneaker", "athletic shoe", "shoe", "shoebox", "person", "face", "baby", "child",
         "document", "receipt", "food", "car"]
SHOES = {"sneaker", "athletic shoe", "shoe", "shoebox"}
PEOPLE = {"person", "face", "baby", "child"}


@contextmanager
def offline():
    def blocked(*args, **kwargs):
        raise PermissionError("Network access is disabled for local triage")
    with patch.object(socket.socket, 'connect', blocked), patch.object(socket.socket, 'connect_ex', blocked), patch.object(socket, 'getaddrinfo', blocked):
        yield


class LocalDetector:
    def __init__(self, weights):
        if not weights.is_file():
            raise ValueError('A previously downloaded local weights file is required')
        os.environ['YOLO_OFFLINE'] = 'true'
        os.environ['YOLO_VERBOSE'] = 'false'
        from ultralytics import YOLOWorld
        import torch
        self.device = 'mps' if torch.backends.mps.is_available() else 'cpu'
        self.model = YOLOWorld(str(weights))
        self.model.set_classes(VOCAB)

    def __call__(self, paths):
        predictions = self.model.predict(paths, batch=len(paths), conf=.18, device=self.device, verbose=False)
        results=[]
        for prediction in predictions:
            shoe=person=0.;boxes=[]
            for box in prediction.boxes:
                name=VOCAB[int(box.cls[0].item())];confidence=float(box.conf[0].item())
                boxes.append({'class':name,'conf':round(confidence,3)})
                if name in SHOES:shoe=max(shoe,confidence)
                elif name in PEOPLE:person=max(person,confidence)
            # Retain the established candidate categories, always as unreviewed suggestions.
            category='non_personal' if shoe>=.2 else 'personal' if person>=.2 else 'unknown'
            results.append({'category':category,'shoe_conf':round(shoe,3),'person_conf':round(person,3),'detections':boxes})
        return results


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db')
    parser.add_argument('--repair',action='store_true')
    parser.add_argument('--apply',action='store_true',help='Commit the explicit repair; default repair is a rollback-only preview')
    parser.add_argument('--legacy-tail',type=int,default=0)
    parser.add_argument('--weights',type=Path,default=Path(__file__).resolve().parents[1]/'yolov8s-worldv2.pt')
    parser.add_argument('--limit',type=int,default=0)
    parser.add_argument('--batch-size',type=int,default=16)
    args=parser.parse_args();db=LibraryDB(args.db)
    if args.repair:
        print(json.dumps(repair_catalog(db,legacy_tail=args.legacy_tail,apply=args.apply),sort_keys=True));return 0
    if args.apply or args.legacy_tail:
        parser.error('--apply and --legacy-tail are only used with --repair')
    stopping=False
    def stop(*_):
        nonlocal stopping
        stopping=True
    signal.signal(signal.SIGINT,stop);signal.signal(signal.SIGTERM,stop)
    with args.weights.open('rb') as stream:model_sha=hashlib.file_digest(stream,'sha256').hexdigest()
    with offline():
        detector=LocalDetector(args.weights)
        result=run_triage(db,detector,model_sha256=model_sha,batch_size=args.batch_size,limit=args.limit,
                          stopping=lambda:stopping,progress=lambda p:print('SACC_TRIAGE_PROGRESS '+json.dumps(p),flush=True))
    print('SACC_TRIAGE_RESULT '+json.dumps(result),flush=True)
    return 2 if result['retryable_remaining'] else 0


if __name__=='__main__':
    raise SystemExit(main())
