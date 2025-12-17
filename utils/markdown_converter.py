"""
Markdown converter for converting Bitbucket markdown to GitHub-compatible markdown
"""
import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class MarkdownConverter:
    """Converts Bitbucket markdown syntax to GitHub-compatible markdown"""
    
    def __init__(self):
        """Initialize the markdown converter"""
        self.conversion_count = 0
    
    def convert(self, text: Optional[str]) -> str:
        """
        Convert Bitbucket markdown to GitHub markdown
        
        Args:
            text: Bitbucket markdown text
            
        Returns:
            GitHub-compatible markdown
        """
        if not text:
            return ""
        
        converted = text
        
        # Convert headings - Bitbucket and GitHub use same syntax (#, ##, ###)
        # No conversion needed for headings
        
        # Convert bold text - Both use ** or __ 
        # No conversion needed
        
        # Convert italic text - Both use * or _
        # No conversion needed
        
        # Convert code blocks - Both use ``` or ~~~
        # No conversion needed
        
        # Convert inline code - Both use `
        # No conversion needed
        
        # Convert strikethrough - Both use ~~
        # No conversion needed
        
        # Convert links - Both use [text](url)
        # No conversion needed
        
        # Convert images - Both use ![alt](url)
        # No conversion needed
        
        # Convert tables - Both use pipe syntax
        # No conversion needed
        
        # Convert ordered lists - Both use 1. 2. 3.
        # No conversion needed
        
        # Convert unordered lists - Both use -, *, +
        # No conversion needed
        
        # Convert blockquotes - Both use >
        # No conversion needed
        
        # Convert horizontal rules - Both use ---, ***, ___
        # No conversion needed
        
        # Convert task lists - Both use - [ ] and - [x]
        # No conversion needed
        
        # Convert user mentions
        converted = self._convert_mentions(converted)
        
        # Convert emoji shortcodes - Both use :emoji:
        # No conversion needed
        
        # Convert Bitbucket-specific syntax
        converted = self._convert_bitbucket_specific(converted)
        
        return converted
    
    def _convert_mentions(self, text: str) -> str:
        """
        Convert Bitbucket @mentions to GitHub @mentions
        Bitbucket uses @{username} or @{userid:uuid} or @username
        GitHub uses @username
        
        Args:
            text: Text with Bitbucket mentions
            
        Returns:
            Text with GitHub mentions
        """
        # Note: UUID-style mentions (@{userid:uuid}) are handled in GitHub client
        # with proper user mapping, so we don't convert them here
        
        # Convert @{username} to @username (alphanumeric usernames)
        text = re.sub(r'@\{([a-zA-Z0-9_-]+)\}', r'@\1', text)
        
        # @username format is already compatible
        
        return text
    
    def _convert_bitbucket_specific(self, text: str) -> str:
        """
        Convert Bitbucket-specific markdown features to GitHub equivalents
        
        Args:
            text: Text with Bitbucket-specific markdown
            
        Returns:
            Text with GitHub-compatible markdown
        """
        # Remove Bitbucket markdown attributes (e.g., {: data-layout='center' })
        # These appear after images and other elements
        text = re.sub(r'\{:[^}]+\}', '', text)
        
        # Bitbucket color markers (not supported in GitHub)
        # {color:red}text{color} -> **text** (use bold as fallback)
        text = re.sub(r'\{color:[^}]+\}([^{]+)\{color\}', r'**\1**', text)
        
        # Bitbucket panels
        # {panel:title=Title}content{panel} -> ### Title\n> content
        def convert_panel(match):
            title = match.group(1) if match.group(1) else "Note"
            content = match.group(2)
            return f"### {title}\n> {content}"
        
        text = re.sub(r'\{panel(?::title=([^}]+))?\}(.*?)\{panel\}', convert_panel, text, flags=re.DOTALL)
        
        # Bitbucket info/tip/note/warning macros
        # {info}text{info} -> > ℹ️ **Info:** text
        text = re.sub(r'\{info\}(.*?)\{info\}', r'> ℹ️ **Info:** \1', text, flags=re.DOTALL)
        text = re.sub(r'\{tip\}(.*?)\{tip\}', r'> 💡 **Tip:** \1', text, flags=re.DOTALL)
        text = re.sub(r'\{note\}(.*?)\{note\}', r'> 📝 **Note:** \1', text, flags=re.DOTALL)
        text = re.sub(r'\{warning\}(.*?)\{warning\}', r'> ⚠️ **Warning:** \1', text, flags=re.DOTALL)
        
        # Bitbucket code macro with language
        # {code:language}text{code} -> ```language\ntext\n```
        def convert_code_macro(match):
            lang = match.group(1) if match.group(1) else ""
            code = match.group(2)
            return f"```{lang}\n{code}\n```"
        
        text = re.sub(r'\{code(?::([^}]+))?\}(.*?)\{code\}', convert_code_macro, text, flags=re.DOTALL)
        
        # Bitbucket quote macro
        # {quote}text{quote} -> > text
        text = re.sub(r'\{quote\}(.*?)\{quote\}', r'> \1', text, flags=re.DOTALL)
        
        # Bitbucket anchor links
        # {anchor:name} -> <a id="name"></a>
        text = re.sub(r'\{anchor:([^}]+)\}', r'<a id="\1"></a>', text)
        
        # Bitbucket noformat (preformatted text)
        # {noformat}text{noformat} -> ```\ntext\n```
        text = re.sub(r'\{noformat\}(.*?)\{noformat\}', r'```\n\1\n```', text, flags=re.DOTALL)
        
        return text
    
    def convert_pr_description(self, description: Optional[str]) -> str:
        """
        Convert PR description from Bitbucket markdown to GitHub markdown
        
        Args:
            description: PR description in Bitbucket markdown
            
        Returns:
            PR description in GitHub markdown
        """
        if not description:
            return ""
        
        converted = self.convert(description)
        logger.debug("Converted PR description markdown")
        return converted
    
    def convert_comment(self, comment_text: Optional[str]) -> str:
        """
        Convert comment text from Bitbucket markdown to GitHub markdown
        
        Args:
            comment_text: Comment text in Bitbucket markdown
            
        Returns:
            Comment text in GitHub markdown
        """
        if not comment_text:
            return ""
        
        converted = self.convert(comment_text)
        logger.debug("Converted comment markdown")
        return converted
