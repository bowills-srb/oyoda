# STR Data Collector MCP Server

An MCP (Model Context Protocol) server that helps collect property data from an operator's local files during onboarding.

## What It Does

The STR Data Collector scans local files and extracts property information:

- **Spreadsheets** (Excel, CSV) - Property lists, rate sheets, owner contacts
- **Documents** (Word, PDF) - House manuals, welcome guides, contracts
- **Text files** - Notes, instructions, checklists

### Data Extracted

- WiFi network names and passwords
- Door codes and gate codes
- Check-in/out times
- Property details (bedrooms, bathrooms, sleeps)
- Addresses
- Property codes/names

## Installation

```bash
cd mcp_servers/str-data-collector
npm install
```

## Claude Desktop Configuration

Add to your Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "str-data-collector": {
      "command": "node",
      "args": ["/path/to/STR-Beach_Habitats/mcp_servers/str-data-collector/src/index.js"],
      "env": {}
    }
  }
}
```

## Tools Available

### `scan_directory`
Scan a directory for property-related files.

```
Input: { "path": "~/Documents/Properties", "recursive": true }
Output: List of spreadsheets, documents, and data files found
```

### `analyze_file`
Extract property data from a specific file.

```
Input: { "path": "~/Documents/SeaLaVie-Manual.docx" }
Output: Extracted WiFi, codes, check-in times, etc.
```

### `analyze_spreadsheet`
Parse Excel/CSV files and return structured data.

```
Input: { "path": "~/Documents/PropertyList.xlsx", "sheetName": "Properties" }
Output: JSON array of property records
```

### `extract_property_info`
Extract property data from raw text.

```
Input: { "text": "WiFi: BeachHouse, Password: summer2024, Door code: 1234" }
Output: { wifi: ["BeachHouse"], passwords: ["summer2024"], doorCodes: ["1234"] }
```

### `batch_analyze`
Analyze multiple files at once.

```
Input: { "paths": ["file1.xlsx", "file2.docx"], "maxFiles": 50 }
Output: Consolidated analysis results
```

### `find_property_files`
Search for files related to a specific property.

```
Input: { "searchPath": "~/Documents", "propertyCode": "SEALAVIE" }
Output: Files matching the property code
```

### `build_property_database`
Compile extracted data into a unified property database.

```
Input: { "analyzedFiles": [...], "operatorId": "op_beach_habitats" }
Output: Structured property database ready for import
```

## Example Workflow

1. **Operator provides access to their files directory**:
   ```
   "Please scan ~/Dropbox/Beach Habitats for property data"
   ```

2. **Agent scans and finds files**:
   ```
   Found:
   - 3 spreadsheets (PropertyMaster.xlsx, Rates2024.csv, OwnerContacts.xlsx)
   - 15 documents (house manuals, welcome guides)
   - 5 data files (JSON configs)
   ```

3. **Agent analyzes key files**:
   ```
   PropertyMaster.xlsx contains 43 properties with codes, addresses, and basic info
   House manuals contain WiFi/door codes for 38 properties
   ```

4. **Agent builds property database**:
   ```
   Compiled 43 properties:
   - 38 have WiFi credentials
   - 41 have door codes
   - 43 have check-in/out times
   ```

5. **Data imports into concierge system**

## Security Notes

- The MCP server only has read access to specified directories
- No data is sent externally - all processing is local
- Operator must explicitly grant directory access
- Credentials are stored securely in the concierge system's vault

## Supported File Types

| Type | Extensions | Parser Used |
|------|------------|-------------|
| Excel | .xlsx, .xls | xlsx |
| CSV | .csv, .tsv | csv-parse |
| Word | .docx | mammoth |
| PDF | .pdf | pdf-parse |
| Text | .txt, .md | native |
| JSON | .json | native |

## Data Patterns Detected

The server looks for common patterns in property documents:

```javascript
// WiFi
"WiFi: NetworkName" or "Network: NetworkName"
"Password: secret123" or "WiFi Password: secret123"

// Access codes
"Door code: 1234" or "Entry code: 1234"
"Gate code: 5678" or "Community code: 5678"

// Times
"Check-in: 4pm" or "Check-in time: 4:00 PM"
"Check-out: 10am" or "Checkout: 10:00 AM"

// Property details
"4 bedrooms" or "4BR"
"3.5 bathrooms" or "3.5 BA"
"Sleeps 10" or "Max guests: 10"
```

## Integration with Onboarding Agent

The STR Data Collector integrates with the onboarding flow:

1. During onboarding, operator chooses "Import from local files"
2. Operator grants access to their property data directory
3. MCP server scans and extracts data
4. Onboarding agent presents findings for verification
5. Verified data is imported into the knowledge base

This is faster and more accurate than manual entry, especially for operators with 10+ properties.
