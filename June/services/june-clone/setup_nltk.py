#!/usr/bin/env python3
"""
setup_nltk.py - NLTK data setup for June TTS
This script downloads all required NLTK datasets for TTS synthesis
"""

import nltk
import ssl
import os
import sys

def setup_ssl():
    """Handle SSL certificate issues for NLTK downloads"""
    try:
        _create_unverified_https_context = ssl._create_unverified_context
    except AttributeError:
        pass
    else:
        ssl._create_default_https_context = _create_unverified_https_context

def download_nltk_data():
    """Download all required NLTK datasets"""
    # Set download directory
    nltk_data_dir = '/home/appuser/nltk_data'
    os.makedirs(nltk_data_dir, exist_ok=True)
    
    # List of required datasets
    datasets = [
        'averaged_perceptron_tagger_eng',
        'averaged_perceptron_tagger', 
        'punkt',
        'punkt_tab',
        'cmudict',
        'wordnet',
        'stopwords'
    ]
    
    print("📥 Downloading NLTK data to fix TTS synthesis...")
    
    success_count = 0
    for dataset in datasets:
        try:
            result = nltk.download(dataset, download_dir=nltk_data_dir, quiet=True)
            if result:
                print(f"✅ Downloaded {dataset}")
                success_count += 1
            else:
                print(f"⚠️ {dataset} may already exist or download failed")
        except Exception as e:
            print(f"⚠️ Failed to download {dataset}: {e}")
    
    print(f"🎉 NLTK data setup complete! Downloaded {success_count}/{len(datasets)} datasets")
    
    # Verify critical datasets
    verify_datasets(nltk_data_dir)

def verify_datasets(nltk_data_dir):
    """Verify that critical datasets are available"""
    try:
        nltk.data.find('taggers/averaged_perceptron_tagger_eng', paths=[nltk_data_dir])
        print("✅ Critical tagger found: averaged_perceptron_tagger_eng")
    except:
        print("❌ Critical tagger missing: averaged_perceptron_tagger_eng")
        try:
            nltk.data.find('taggers/averaged_perceptron_tagger', paths=[nltk_data_dir])
            print("✅ Fallback tagger found: averaged_perceptron_tagger")
        except:
            print("❌ No taggers found - TTS may fail")
            sys.exit(1)

if __name__ == "__main__":
    setup_ssl()
    download_nltk_data()
    print("✅ NLTK setup completed successfully!")