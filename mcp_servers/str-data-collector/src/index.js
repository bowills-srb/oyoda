#!/usr/bin/env node
/**
 * STR Data Collector MCP Server
 * 
 * An MCP server that helps collect property data from an operator's local files:
 * - Excel/CSV spreadsheets
 * - Word documents (house manuals, guides)
 * - PDFs (contracts, welcome packets)
 * - Text files
 * - Images (property photos)
 * 
 * The agent can:
 * 1. Scan directories for property-related files
 * 2. Extract structured data from spreadsheets
 * 3. Parse text from documents
 * 4. Identify property names/codes from file names
 * 5. Build a unified property database
 */

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
  ListResourcesRequestSchema,
  ReadResourceRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";

import fs from "fs/promises";
import path from "path";
import { glob } from "glob";
import mime from "mime-types";

// Dynamic imports for document parsing
let xlsx, pdfParse, mammoth, csvParse;

async function loadParsers() {
  try {
    xlsx = (await import("xlsx")).default;
  } catch (e) {
    console.error("xlsx not available:", e.message);
  }
  
  try {
    pdfParse = (await import("pdf-parse")).default;
  } catch (e) {
    console.error("pdf-parse not available:", e.message);
  }
  
  try {
    mammoth = await import("mammoth");
  } catch (e) {
    console.error("mammoth not available:", e.message);
  }
  
  try {
    csvParse = (await import("csv-parse/sync")).parse;
  } catch (e) {
    console.error("csv-parse not available:", e.message);
  }
}

// Property data patterns to look for
const PROPERTY_PATTERNS = {
  // Common property identifier patterns
  propertyCode: /\b([A-Z]{2,}[-_]?\d{0,4}|[A-Z]{3,12})\b/g,
  
  // WiFi patterns
  wifi: /(?:wifi|wi-fi|wireless|network)\s*[:=]?\s*["']?([^"'\n,]+)["']?/gi,
  wifiPassword: /(?:password|pwd|pass|key)\s*[:=]?\s*["']?([^"'\n,]+)["']?/gi,
  
  // Access codes
  doorCode: /(?:door|entry|access|lock|keypad)\s*(?:code)?\s*[:=]?\s*["']?(\d{4,6})["']?/gi,
  gateCode: /(?:gate|community)\s*(?:code)?\s*[:=]?\s*["']?(\d{4,6})["']?/gi,
  
  // Times
  checkIn: /(?:check[-\s]?in)\s*(?:time)?\s*[:=]?\s*["']?(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)/gi,
  checkOut: /(?:check[-\s]?out)\s*(?:time)?\s*[:=]?\s*["']?(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)/gi,
  
  // Property details
  bedrooms: /(\d+)\s*(?:bed(?:room)?s?|br|bdrm)/gi,
  bathrooms: /(\d+(?:\.\d)?)\s*(?:bath(?:room)?s?|ba)/gi,
  sleeps: /(?:sleeps?|max\s*guests?|occupancy)\s*[:=]?\s*(\d+)/gi,
  
  // Address patterns
  address: /(\d+\s+[A-Za-z\s]+(?:St|Street|Ave|Avenue|Rd|Road|Dr|Drive|Ln|Lane|Blvd|Way|Circle|Ct|Court)[^,\n]*)/gi,
};

// File types we can process
const SUPPORTED_EXTENSIONS = {
  spreadsheet: [".xlsx", ".xls", ".csv", ".tsv"],
  document: [".docx", ".doc", ".pdf", ".txt", ".md", ".rtf"],
  image: [".jpg", ".jpeg", ".png", ".gif", ".webp"],
  data: [".json", ".xml", ".yaml", ".yml"],
};

/**
 * Extract text content from various file types
 */
async function extractFileContent(filePath) {
  const ext = path.extname(filePath).toLowerCase();
  const content = { raw: "", structured: null, type: ext };
  
  try {
    if (SUPPORTED_EXTENSIONS.spreadsheet.includes(ext)) {
      content.structured = await parseSpreadsheet(filePath);
      content.raw = JSON.stringify(content.structured, null, 2);
    } else if (ext === ".pdf" && pdfParse) {
      const buffer = await fs.readFile(filePath);
      const data = await pdfParse(buffer);
      content.raw = data.text;
    } else if (ext === ".docx" && mammoth) {
      const buffer = await fs.readFile(filePath);
      const result = await mammoth.extractRawText({ buffer });
      content.raw = result.value;
    } else if ([".txt", ".md", ".json", ".xml", ".yaml", ".yml"].includes(ext)) {
      content.raw = await fs.readFile(filePath, "utf-8");
      if (ext === ".json") {
        try {
          content.structured = JSON.parse(content.raw);
        } catch (e) {}
      }
    }
  } catch (error) {
    content.error = error.message;
  }
  
  return content;
}

/**
 * Parse spreadsheet files (Excel, CSV)
 */
async function parseSpreadsheet(filePath) {
  const ext = path.extname(filePath).toLowerCase();
  
  if (ext === ".csv" || ext === ".tsv") {
    const content = await fs.readFile(filePath, "utf-8");
    if (csvParse) {
      return csvParse(content, {
        columns: true,
        skip_empty_lines: true,
        delimiter: ext === ".tsv" ? "\t" : ",",
      });
    }
    return { raw: content };
  }
  
  if (xlsx && (ext === ".xlsx" || ext === ".xls")) {
    const workbook = xlsx.readFile(filePath);
    const sheets = {};
    
    for (const sheetName of workbook.SheetNames) {
      const sheet = workbook.Sheets[sheetName];
      sheets[sheetName] = xlsx.utils.sheet_to_json(sheet, { defval: "" });
    }
    
    return sheets;
  }
  
  return null;
}

/**
 * Extract property data from text content
 */
function extractPropertyData(text, fileName = "") {
  const data = {
    possiblePropertyCodes: [],
    wifi: [],
    passwords: [],
    doorCodes: [],
    gateCodes: [],
    checkInTimes: [],
    checkOutTimes: [],
    bedrooms: [],
    bathrooms: [],
    sleeps: [],
    addresses: [],
  };
  
  // Try to get property code from filename
  const fileNameMatch = fileName.match(/^([A-Z]{2,}[-_]?\d{0,4}|[A-Z]{3,12})/i);
  if (fileNameMatch) {
    data.possiblePropertyCodes.push(fileNameMatch[1].toUpperCase());
  }
  
  // Extract patterns from text
  for (const [key, pattern] of Object.entries(PROPERTY_PATTERNS)) {
    const matches = text.matchAll(pattern);
    for (const match of matches) {
      if (match[1] && !data[key]?.includes(match[1])) {
        if (key === "propertyCode") {
          data.possiblePropertyCodes.push(match[1]);
        } else if (key === "wifi") {
          data.wifi.push(match[1].trim());
        } else if (key === "wifiPassword") {
          data.passwords.push(match[1].trim());
        } else if (key === "doorCode") {
          data.doorCodes.push(match[1]);
        } else if (key === "gateCode") {
          data.gateCodes.push(match[1]);
        } else if (key === "checkIn") {
          data.checkInTimes.push(match[1]);
        } else if (key === "checkOut") {
          data.checkOutTimes.push(match[1]);
        } else if (key === "bedrooms") {
          data.bedrooms.push(parseInt(match[1]));
        } else if (key === "bathrooms") {
          data.bathrooms.push(parseFloat(match[1]));
        } else if (key === "sleeps") {
          data.sleeps.push(parseInt(match[1]));
        } else if (key === "address") {
          data.addresses.push(match[1].trim());
        }
      }
    }
  }
  
  // Deduplicate
  for (const key of Object.keys(data)) {
    if (Array.isArray(data[key])) {
      data[key] = [...new Set(data[key])];
    }
  }
  
  return data;
}

/**
 * Scan directory for property-related files
 */
async function scanDirectory(dirPath, options = {}) {
  const { recursive = true, maxDepth = 5 } = options;
  
  const allExtensions = [
    ...SUPPORTED_EXTENSIONS.spreadsheet,
    ...SUPPORTED_EXTENSIONS.document,
    ...SUPPORTED_EXTENSIONS.data,
  ];
  
  const pattern = recursive
    ? `${dirPath}/**/*{${allExtensions.join(",")}}`
    : `${dirPath}/*{${allExtensions.join(",")}}`;
  
  const files = await glob(pattern, {
    nocase: true,
    maxDepth: recursive ? maxDepth : 1,
    ignore: [
      "**/node_modules/**",
      "**/.git/**",
      "**/venv/**",
      "**/__pycache__/**",
    ],
  });
  
  return files;
}

/**
 * Analyze a file and extract property data
 */
async function analyzeFile(filePath) {
  const stats = await fs.stat(filePath);
  const fileName = path.basename(filePath);
  const ext = path.extname(filePath).toLowerCase();
  
  const result = {
    path: filePath,
    fileName,
    extension: ext,
    size: stats.size,
    modified: stats.mtime,
    type: getFileType(ext),
    content: null,
    extractedData: null,
  };
  
  // Extract content for non-image files
  if (result.type !== "image" && stats.size < 10 * 1024 * 1024) {
    result.content = await extractFileContent(filePath);
    
    // Extract property data from content
    if (result.content.raw) {
      result.extractedData = extractPropertyData(result.content.raw, fileName);
    }
  }
  
  return result;
}

function getFileType(ext) {
  for (const [type, extensions] of Object.entries(SUPPORTED_EXTENSIONS)) {
    if (extensions.includes(ext)) return type;
  }
  return "unknown";
}

// Create MCP Server
const server = new Server(
  {
    name: "str-data-collector",
    version: "1.0.0",
  },
  {
    capabilities: {
      tools: {},
      resources: {},
    },
  }
);

// Tool definitions
const TOOLS = [
  {
    name: "scan_directory",
    description: `Scan a directory for STR property-related files (spreadsheets, documents, PDFs). 
Returns a list of files that likely contain property data.
Use this to discover where property information is stored.`,
    inputSchema: {
      type: "object",
      properties: {
        path: {
          type: "string",
          description: "Directory path to scan (e.g., ~/Documents/Properties or /Users/john/Dropbox/STR)",
        },
        recursive: {
          type: "boolean",
          description: "Whether to scan subdirectories (default: true)",
          default: true,
        },
        maxDepth: {
          type: "number",
          description: "Maximum directory depth to scan (default: 5)",
          default: 5,
        },
      },
      required: ["path"],
    },
  },
  {
    name: "analyze_file",
    description: `Analyze a specific file and extract property data.
Supports: Excel (.xlsx, .xls), CSV, Word (.docx), PDF, text files.
Extracts: WiFi credentials, door codes, check-in/out times, property details.`,
    inputSchema: {
      type: "object",
      properties: {
        path: {
          type: "string",
          description: "Path to the file to analyze",
        },
      },
      required: ["path"],
    },
  },
  {
    name: "analyze_spreadsheet",
    description: `Specifically analyze a spreadsheet file (Excel, CSV) for property data.
Returns structured data with column headers and rows.
Best for property lists, rate sheets, owner contacts.`,
    inputSchema: {
      type: "object",
      properties: {
        path: {
          type: "string",
          description: "Path to the spreadsheet file",
        },
        sheetName: {
          type: "string",
          description: "Specific sheet name to analyze (Excel only, optional)",
        },
      },
      required: ["path"],
    },
  },
  {
    name: "extract_property_info",
    description: `Extract property information from a text string.
Finds: WiFi networks/passwords, door codes, check-in times, addresses, bedroom/bathroom counts.
Use this to parse text you've already retrieved.`,
    inputSchema: {
      type: "object",
      properties: {
        text: {
          type: "string",
          description: "Text content to analyze for property data",
        },
        fileName: {
          type: "string",
          description: "Optional filename to help identify property code",
        },
      },
      required: ["text"],
    },
  },
  {
    name: "batch_analyze",
    description: `Analyze multiple files at once and compile property data.
Use after scan_directory to process discovered files.
Returns consolidated property information.`,
    inputSchema: {
      type: "object",
      properties: {
        paths: {
          type: "array",
          items: { type: "string" },
          description: "Array of file paths to analyze",
        },
        maxFiles: {
          type: "number",
          description: "Maximum number of files to process (default: 50)",
          default: 50,
        },
      },
      required: ["paths"],
    },
  },
  {
    name: "find_property_files",
    description: `Search for files related to a specific property.
Searches file names and content for property code/name matches.`,
    inputSchema: {
      type: "object",
      properties: {
        searchPath: {
          type: "string",
          description: "Directory to search in",
        },
        propertyCode: {
          type: "string",
          description: "Property code to search for (e.g., 'SEALAVIE', 'BH-001')",
        },
        propertyName: {
          type: "string",
          description: "Property name to search for (e.g., 'Sea La Vie')",
        },
      },
      required: ["searchPath"],
    },
  },
  {
    name: "build_property_database",
    description: `Compile all extracted data into a structured property database.
Takes analyzed files and creates a unified JSON structure.
Ready to import into the concierge system.`,
    inputSchema: {
      type: "object",
      properties: {
        analyzedFiles: {
          type: "array",
          description: "Array of file analysis results from batch_analyze",
        },
        operatorId: {
          type: "string",
          description: "Operator ID to associate with properties",
        },
      },
      required: ["analyzedFiles", "operatorId"],
    },
  },
];

// Handle tool listing
server.setRequestHandler(ListToolsRequestSchema, async () => {
  return { tools: TOOLS };
});

// Handle tool execution
server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;
  
  try {
    switch (name) {
      case "scan_directory": {
        const expandedPath = args.path.replace(/^~/, process.env.HOME || "");
        const files = await scanDirectory(expandedPath, {
          recursive: args.recursive ?? true,
          maxDepth: args.maxDepth ?? 5,
        });
        
        // Categorize files
        const categorized = {
          spreadsheets: files.filter(f => SUPPORTED_EXTENSIONS.spreadsheet.includes(path.extname(f).toLowerCase())),
          documents: files.filter(f => SUPPORTED_EXTENSIONS.document.includes(path.extname(f).toLowerCase())),
          data: files.filter(f => SUPPORTED_EXTENSIONS.data.includes(path.extname(f).toLowerCase())),
          total: files.length,
        };
        
        return {
          content: [
            {
              type: "text",
              text: JSON.stringify(categorized, null, 2),
            },
          ],
        };
      }
      
      case "analyze_file": {
        const expandedPath = args.path.replace(/^~/, process.env.HOME || "");
        const result = await analyzeFile(expandedPath);
        
        return {
          content: [
            {
              type: "text",
              text: JSON.stringify(result, null, 2),
            },
          ],
        };
      }
      
      case "analyze_spreadsheet": {
        const expandedPath = args.path.replace(/^~/, process.env.HOME || "");
        const data = await parseSpreadsheet(expandedPath);
        
        let result = data;
        if (args.sheetName && data[args.sheetName]) {
          result = data[args.sheetName];
        }
        
        return {
          content: [
            {
              type: "text",
              text: JSON.stringify(result, null, 2),
            },
          ],
        };
      }
      
      case "extract_property_info": {
        const extracted = extractPropertyData(args.text, args.fileName || "");
        
        return {
          content: [
            {
              type: "text",
              text: JSON.stringify(extracted, null, 2),
            },
          ],
        };
      }
      
      case "batch_analyze": {
        const maxFiles = args.maxFiles || 50;
        const paths = args.paths.slice(0, maxFiles);
        const results = [];
        
        for (const filePath of paths) {
          try {
            const expandedPath = filePath.replace(/^~/, process.env.HOME || "");
            const result = await analyzeFile(expandedPath);
            results.push(result);
          } catch (error) {
            results.push({
              path: filePath,
              error: error.message,
            });
          }
        }
        
        return {
          content: [
            {
              type: "text",
              text: JSON.stringify({
                analyzed: results.length,
                results,
              }, null, 2),
            },
          ],
        };
      }
      
      case "find_property_files": {
        const expandedPath = args.searchPath.replace(/^~/, process.env.HOME || "");
        const allFiles = await scanDirectory(expandedPath);
        const matches = [];
        
        const searchTerms = [
          args.propertyCode?.toLowerCase(),
          args.propertyName?.toLowerCase(),
        ].filter(Boolean);
        
        for (const filePath of allFiles) {
          const fileName = path.basename(filePath).toLowerCase();
          
          // Check filename
          if (searchTerms.some(term => fileName.includes(term))) {
            matches.push({ path: filePath, matchType: "filename" });
            continue;
          }
          
          // Check content for text files
          const ext = path.extname(filePath).toLowerCase();
          if ([".txt", ".md", ".csv", ".json"].includes(ext)) {
            try {
              const content = await fs.readFile(filePath, "utf-8");
              if (searchTerms.some(term => content.toLowerCase().includes(term))) {
                matches.push({ path: filePath, matchType: "content" });
              }
            } catch (e) {}
          }
        }
        
        return {
          content: [
            {
              type: "text",
              text: JSON.stringify({
                searchTerms,
                matches,
              }, null, 2),
            },
          ],
        };
      }
      
      case "build_property_database": {
        const properties = new Map();
        
        for (const file of args.analyzedFiles || []) {
          if (!file.extractedData) continue;
          
          const data = file.extractedData;
          const codes = data.possiblePropertyCodes || [];
          
          for (const code of codes) {
            if (!properties.has(code)) {
              properties.set(code, {
                code,
                operator_id: args.operatorId,
                sources: [],
                wifi_network: null,
                wifi_password: null,
                door_code: null,
                gate_code: null,
                check_in_time: null,
                check_out_time: null,
                bedrooms: null,
                bathrooms: null,
                sleeps: null,
                address: null,
              });
            }
            
            const prop = properties.get(code);
            prop.sources.push(file.path);
            
            // Merge data (first non-null wins)
            if (!prop.wifi_network && data.wifi?.[0]) prop.wifi_network = data.wifi[0];
            if (!prop.wifi_password && data.passwords?.[0]) prop.wifi_password = data.passwords[0];
            if (!prop.door_code && data.doorCodes?.[0]) prop.door_code = data.doorCodes[0];
            if (!prop.gate_code && data.gateCodes?.[0]) prop.gate_code = data.gateCodes[0];
            if (!prop.check_in_time && data.checkInTimes?.[0]) prop.check_in_time = data.checkInTimes[0];
            if (!prop.check_out_time && data.checkOutTimes?.[0]) prop.check_out_time = data.checkOutTimes[0];
            if (!prop.bedrooms && data.bedrooms?.[0]) prop.bedrooms = data.bedrooms[0];
            if (!prop.bathrooms && data.bathrooms?.[0]) prop.bathrooms = data.bathrooms[0];
            if (!prop.sleeps && data.sleeps?.[0]) prop.sleeps = data.sleeps[0];
            if (!prop.address && data.addresses?.[0]) prop.address = data.addresses[0];
          }
        }
        
        const database = {
          operator_id: args.operatorId,
          properties: Array.from(properties.values()),
          generated_at: new Date().toISOString(),
        };
        
        return {
          content: [
            {
              type: "text",
              text: JSON.stringify(database, null, 2),
            },
          ],
        };
      }
      
      default:
        throw new Error(`Unknown tool: ${name}`);
    }
  } catch (error) {
    return {
      content: [
        {
          type: "text",
          text: JSON.stringify({ error: error.message }),
        },
      ],
      isError: true,
    };
  }
});

// Start server
async function main() {
  await loadParsers();
  
  const transport = new StdioServerTransport();
  await server.connect(transport);
  
  console.error("STR Data Collector MCP Server running on stdio");
}

main().catch(console.error);
