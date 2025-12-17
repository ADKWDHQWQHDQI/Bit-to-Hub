"""
Image migration utility for downloading images from Bitbucket and uploading to GitHub
"""
import re
import logging
import requests
import base64
import os
from typing import Dict, List, Tuple, Optional
from urllib.parse import urlparse, urljoin, unquote

logger = logging.getLogger(__name__)


class ImageMigrator:
    """Handles migration of images from Bitbucket to GitHub"""
    
    def __init__(self, bitbucket_workspace: str, bitbucket_repo: str, 
                 github_owner: str, github_repo: str, 
                 bitbucket_token: str, github_token: str):
        """
        Initialize image migrator
        
        Args:
            bitbucket_workspace: Bitbucket workspace name
            bitbucket_repo: Bitbucket repository name
            github_owner: GitHub owner (org or user)
            github_repo: GitHub repository name
            bitbucket_token: Bitbucket OAuth access token
            github_token: GitHub personal access token
        """
        self.bitbucket_workspace = bitbucket_workspace
        self.bitbucket_repo = bitbucket_repo
        self.github_owner = github_owner
        self.github_repo = github_repo
        self.bitbucket_token = bitbucket_token
        self.github_token = github_token
        
        # Track migrated images: {original_url: github_url}
        self.image_mapping: Dict[str, str] = {}
        
        # Session for Bitbucket downloads
        self.bitbucket_session = requests.Session()
        self.bitbucket_session.headers.update({
            'Authorization': f'Bearer {bitbucket_token}',
            'Accept': 'application/json'
        })
        
        # Session for GitHub uploads
        self.github_session = requests.Session()
        self.github_session.headers.update({
            'Authorization': f'token {github_token}',
            'Accept': 'application/vnd.github.v3+json'
        })
    
    def extract_image_urls(self, text: str) -> List[str]:
        """
        Extract all image URLs from markdown text
        
        Args:
            text: Markdown text containing images
            
        Returns:
            List of image URLs
        """
        if not text:
            return []
        
        # Pattern: ![alt text](image_url)
        markdown_images = re.findall(r'!\[([^\]]*)\]\(([^)]+)\)', text)
        urls = [url for _, url in markdown_images]
        
        # Also check for HTML img tags
        html_images = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', text)
        urls.extend(html_images)
        
        # Filter only Bitbucket URLs
        bitbucket_urls = [
            url for url in urls 
            if 'bitbucket.org' in url or url.startswith('/')
        ]
        
        return bitbucket_urls
    
    def download_image(self, image_url: str) -> Optional[Tuple[bytes, str]]:
        """
        Download image from Bitbucket
        
        Args:
            image_url: URL of image in Bitbucket
            
        Returns:
            Tuple of (image_data, content_type) or None if failed
        """
        try:
            # Handle relative URLs
            if image_url.startswith('/'):
                # Relative to Bitbucket domain
                image_url = f"https://bitbucket.org{image_url}"
            
            # Download image
            response = self.bitbucket_session.get(image_url, timeout=30)
            response.raise_for_status()
            
            content_type = response.headers.get('Content-Type', 'image/png')
            image_data = response.content
            
            logger.info(f"Downloaded image: {image_url} ({len(image_data)} bytes)")
            return image_data, content_type
        
        except Exception as e:
            logger.error(f"Failed to download image {image_url}: {e}")
            return None
    
    def upload_to_github_issue(self, image_data: bytes, filename: str, 
                                issue_number: int) -> Optional[str]:
        """
        Upload image as GitHub issue attachment
        
        Args:
            image_data: Raw image bytes
            filename: Original filename
            issue_number: GitHub issue/PR number to attach to
            
        Returns:
            GitHub URL of uploaded image or None if failed
        """
        try:
            # GitHub's issue attachment API endpoint
            url = f"https://api.github.com/repos/{self.github_owner}/{self.github_repo}/issues/{issue_number}/assets"
            
            # Prepare multipart upload
            files = {
                'file': (filename, image_data)
            }
            
            response = self.github_session.post(url, files=files, timeout=30)
            
            if response.status_code == 201:
                data = response.json()
                github_url = data.get('browser_download_url', data.get('url'))
                logger.info(f"Uploaded image to GitHub: {github_url}")
                return github_url
            else:
                logger.error(f"Failed to upload image to GitHub: {response.status_code} - {response.text}")
                return None
        
        except Exception as e:
            logger.error(f"Error uploading image to GitHub: {e}")
            return None
    
    def upload_to_github_repo(self, image_data: bytes, filepath: str, 
                               branch: str = "main") -> Optional[str]:
        """
        Upload image directly to GitHub repository
        
        Args:
            image_data: Raw image bytes
            filepath: Path in repository (e.g., "images/screenshot.png")
            branch: Branch to upload to
            
        Returns:
            GitHub URL of uploaded image or None if failed
        """
        try:
            # GitHub's content API endpoint
            url = f"https://api.github.com/repos/{self.github_owner}/{self.github_repo}/contents/{filepath}"
            
            # Check if file already exists
            response = self.github_session.get(url, params={'ref': branch})
            sha = None
            if response.status_code == 200:
                sha = response.json().get('sha')
                logger.info(f"File exists, will update: {filepath}")
            
            # Encode image as base64
            encoded_content = base64.b64encode(image_data).decode('utf-8')
            
            # Prepare upload data
            data = {
                'message': f'Add migrated image: {filepath}',
                'content': encoded_content,
                'branch': branch
            }
            
            if sha:
                data['sha'] = sha  # Update existing file
            
            # Upload
            response = self.github_session.put(url, json=data, timeout=30)
            
            if response.status_code in [200, 201]:
                data = response.json()
                github_url = data['content']['download_url']
                logger.info(f"Uploaded image to GitHub repo: {github_url}")
                return github_url
            else:
                logger.error(f"Failed to upload image to GitHub repo: {response.status_code} - {response.text}")
                return None
        
        except Exception as e:
            logger.error(f"Error uploading image to GitHub repo: {e}")
            return None
    
    def migrate_image(self, image_url: str, pr_number: int, 
                      use_repo_upload: bool = True) -> Optional[str]:
        """
        Migrate a single image from Bitbucket to GitHub
        
        Args:
            image_url: Bitbucket image URL
            pr_number: GitHub PR number (for issue attachment method)
            use_repo_upload: If True, upload to repo; if False, attach to PR
            
        Returns:
            GitHub URL of migrated image or None if failed
        """
        # Check if already migrated
        if image_url in self.image_mapping:
            logger.debug(f"Image already migrated: {image_url}")
            return self.image_mapping[image_url]
        
        # Download from Bitbucket
        download_result = self.download_image(image_url)
        if not download_result:
            return None
        
        image_data, content_type = download_result
        
        # Generate filename
        parsed_url = urlparse(image_url)
        filename = os.path.basename(parsed_url.path) or f"image_{pr_number}.png"
        
        # Decode URL-encoded characters in filename (e.g., %20 -> space, %28 -> ()
        filename = unquote(filename)
        
        # Replace spaces with underscores for better compatibility
        filename = filename.replace(' ', '_')
        
        # Upload to GitHub
        if use_repo_upload:
            # Upload to repository (in images/ directory)
            filepath = f"migrated-images/pr-{pr_number}/{filename}"
            github_url = self.upload_to_github_repo(image_data, filepath)
        else:
            # Attach to PR/issue
            github_url = self.upload_to_github_issue(image_data, filename, pr_number)
        
        if github_url:
            self.image_mapping[image_url] = github_url
        
        return github_url
    
    def migrate_images_in_text(self, text: str, pr_number: int) -> str:
        """
        Find and migrate all images in text, update references
        
        Args:
            text: Markdown text with Bitbucket image URLs
            pr_number: GitHub PR number
            
        Returns:
            Text with updated GitHub image URLs
        """
        if not text:
            return text
        
        # Extract all image URLs
        image_urls = self.extract_image_urls(text)
        
        if not image_urls:
            logger.debug("No Bitbucket images found in text")
            return text
        
        logger.info(f"Found {len(image_urls)} Bitbucket images to migrate")
        
        # Migrate each image and update text
        updated_text = text
        for image_url in image_urls:
            github_url = self.migrate_image(image_url, pr_number, use_repo_upload=True)
            
            if github_url:
                # Replace all occurrences of old URL with new URL
                updated_text = updated_text.replace(image_url, github_url)
                logger.info(f"Replaced: {image_url} -> {github_url}")
            else:
                logger.warning(f"Failed to migrate image, keeping original URL: {image_url}")
        
        return updated_text
    
    def migrate_attachment(self, attachment_url: str, filename: str, pr_number: int) -> Optional[str]:
        """
        Download and migrate a comment attachment file from Bitbucket to GitHub
        
        Args:
            attachment_url: Bitbucket attachment download URL
            filename: Original filename
            pr_number: GitHub PR number
            
        Returns:
            GitHub URL of uploaded attachment or None if failed
        """
        logger.info(f"Migrating attachment: {filename}")
        
        try:
            # Download attachment from Bitbucket
            logger.debug(f"Downloading from: {attachment_url}")
            response = self.bitbucket_session.get(attachment_url)
            response.raise_for_status()
            
            attachment_data = response.content
            logger.info(f"Downloaded {len(attachment_data)} bytes for {filename}")
            
            # Determine if this is an image based on content type or extension
            content_type = response.headers.get('Content-Type', '')
            is_image = (
                'image' in content_type or 
                filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp'))
            )
            
            if is_image:
                # Upload to GitHub repository (works for images)
                logger.debug(f"Uploading image attachment to GitHub repository")
                filepath = f"migrated-images/pr-{pr_number}/{filename}"
                github_url = self.upload_to_github_repo(attachment_data, filepath)
            else:
                # For non-image files, we need to use GitHub's issue attachment API
                # However, this requires creating a comment first, so we'll return the data
                # and let the caller handle it
                logger.warning(f"Non-image attachment {filename} - uploading as file to repository")
                filepath = f"migrated-attachments/pr-{pr_number}/{filename}"
                github_url = self.upload_to_github_repo(attachment_data, filepath)
            
            if github_url:
                logger.info(f"Successfully migrated attachment {filename} to {github_url}")
                return github_url
            else:
                logger.error(f"Failed to upload attachment {filename}")
                return None
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to download attachment {filename}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error migrating attachment {filename}: {e}")
            return None
    
    def get_migration_summary(self) -> Dict[str, int]:
        """
        Get summary of image migration
        
        Returns:
            Dictionary with migration statistics
        """
        return {
            'total_images_migrated': len(self.image_mapping),
            'successful': len([url for url in self.image_mapping.values() if url]),
            'failed': len([url for url in self.image_mapping.values() if not url])
        }
