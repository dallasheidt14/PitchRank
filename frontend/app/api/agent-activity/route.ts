import { NextResponse } from 'next/server';
import * as fs from 'fs/promises';
import * as path from 'path';
import * as os from 'os';

interface SessionMessage {
  type: string;
  timestamp: string;
  message?: {
    role: string;
    content: Array<{
      type: string;
      text?: string;
      name?: string;
      arguments?: any;
    }>;
  };
}

interface AgentMessage {
  timestamp: string;
  agentName: string;
  agentEmoji: string;
  messagePreview: string;
  fullMessage: string;
  sessionId: string;
}

// Map session filenames to agent names
const AGENT_MAP: Record<string, { name: string; emoji: string }> = {
  scrappy: { name: 'Scrappy', emoji: '🕷️' },
  cleany: { name: 'Cleany', emoji: '🧹' },
  watchy: { name: 'Watchy', emoji: '👀' },
  compy: { name: 'Compy', emoji: '🧠' },
  ranky: { name: 'Ranky', emoji: '📊' },
  movy: { name: 'Movy', emoji: '🎬' },
  codey: { name: 'Codey', emoji: '💻' },
  socialy: { name: 'Socialy', emoji: '📱' },
  main: { name: 'Main Agent', emoji: '🤖' },
  subagent: { name: 'Sub-Agent', emoji: '🔧' },
};

function detectAgentFromMessage(message: string): { name: string; emoji: string } {
  // Try to detect agent name from message content
  for (const [key, value] of Object.entries(AGENT_MAP)) {
    if (message.toLowerCase().includes(key) || message.includes(value.emoji)) {
      return value;
    }
  }
  
  // Check for specific agent introductions
  const agentMatch = message.match(/(?:I am|I'm|This is|Here's)\s+([A-Z][a-z]+)\s+[🕷️🧹👀🧠📊🎬💻📱🤖🔧]/);
  if (agentMatch) {
    const name = agentMatch[1];
    const emoji = message.match(/[🕷️🧹👀🧠📊🎬💻📱🤖🔧]/)?.[0] || '🤖';
    return { name, emoji };
  }
  
  return { name: 'Agent', emoji: '🤖' };
}

function extractTextFromContent(content: any[]): string {
  if (!content || !Array.isArray(content)) return '';
  
  const textParts: string[] = [];
  for (const item of content) {
    if (item.type === 'text' && item.text) {
      textParts.push(item.text);
    } else if (item.type === 'toolCall' && item.name) {
      textParts.push(`[Tool: ${item.name}]`);
    }
  }
  
  return textParts.join(' ').trim();
}

function createPreview(text: string, maxLength: number = 150): string {
  if (text.length <= maxLength) return text;
  return text.substring(0, maxLength).trim() + '...';
}

export async function GET() {
  try {
    const sessionsDir = path.join(os.homedir(), '.openclaw', 'agents', 'main', 'sessions');
    
    console.log('[AgentActivity] Checking sessions directory:', sessionsDir);
    
    // Check if directory exists
    try {
      await fs.access(sessionsDir);
      console.log('[AgentActivity] Directory exists and is accessible');
    } catch (accessError) {
      console.error('[AgentActivity] Directory not accessible:', accessError);
      return NextResponse.json(
        { 
          error: 'Sessions directory not found or not accessible',
          messages: [], 
          count: 0,
          debug: { path: sessionsDir, error: String(accessError) }
        },
        { status: 500 }
      );
    }
    
    // Read all session files
    const files = await fs.readdir(sessionsDir);
    const jsonlFiles = files.filter(f => f.endsWith('.jsonl') && !f.includes('.deleted.'));
    
    console.log(`[AgentActivity] Found ${files.length} files, ${jsonlFiles.length} active JSONL files`);
    
    const messages: AgentMessage[] = [];
    let filesProcessed = 0;
    let linesProcessed = 0;
    let messagesExtracted = 0;
    
    // Parse each session file
    for (const file of jsonlFiles) {
      const filePath = path.join(sessionsDir, file);
      const sessionId = file.replace('.jsonl', '');
      
      try {
        const content = await fs.readFile(filePath, 'utf-8');
        const lines = content.split('\n').filter(line => line.trim());
        filesProcessed++;
        
        for (const line of lines) {
          linesProcessed++;
          try {
            const entry: SessionMessage = JSON.parse(line);
            
            // Only process message entries with assistant role
            if (entry.type === 'message' && entry.message?.role === 'assistant') {
              const fullMessage = extractTextFromContent(entry.message.content);
              
              if (fullMessage) {
                const agent = detectAgentFromMessage(fullMessage);
                const preview = createPreview(fullMessage);
                
                messages.push({
                  timestamp: entry.timestamp,
                  agentName: agent.name,
                  agentEmoji: agent.emoji,
                  messagePreview: preview,
                  fullMessage,
                  sessionId,
                });
                messagesExtracted++;
              }
            }
          } catch (parseError) {
            // Skip invalid JSON lines silently
            continue;
          }
        }
      } catch (fileError) {
        console.warn(`[AgentActivity] Could not read file ${file}:`, fileError);
        // Skip files that can't be read
        continue;
      }
    }
    
    console.log(`[AgentActivity] Processed ${filesProcessed} files, ${linesProcessed} lines, extracted ${messagesExtracted} messages`);
    
    // Sort by timestamp (most recent first) and take last 20
    const sortedMessages = messages
      .sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime())
      .slice(0, 20);
    
    console.log(`[AgentActivity] Returning ${sortedMessages.length} messages`);
    
    return NextResponse.json({
      messages: sortedMessages,
      count: sortedMessages.length,
      timestamp: new Date().toISOString(),
    });
  } catch (error) {
    console.error('[AgentActivity] Unexpected error:', error);
    return NextResponse.json(
      { 
        error: 'Failed to read agent activity', 
        messages: [], 
        count: 0,
        debug: { error: String(error) }
      },
      { status: 500 }
    );
  }
}
