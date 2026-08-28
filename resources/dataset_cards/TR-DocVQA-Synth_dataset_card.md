# TR-DocVQA-Synth: A Large-Scale Synthetic Turkish Document Visual Question Answering Dataset

## Dataset Summary

**TR-DocVQA-Synth** is a large-scale synthetic Turkish Document Visual Question Answering dataset designed for training and evaluating multimodal models on Turkish business documents. The dataset contains **15,000 document images** and **235,000 question-answer pairs** generated from structured ground-truth records.

The dataset focuses on realistic Turkish document layouts and field-oriented reasoning. It includes three major document families:

* **e-Fatura / e-Arşiv style invoices**
* **Commercial contracts**
* **Offers, proforma invoices, and purchase/order documents**

Each document is provided as a PNG image, together with structured source metadata and question-answer annotations. The dataset is built to support models that need to read Turkish text from document images, understand document layout, locate key fields, reason over tables, and answer questions using visually grounded document evidence.

At the time of release, **TR-DocVQA-Synth is the first large-scale Turkish-focused Document VQA dataset built specifically around Turkish business documents**. While Turkish text QA and general visual QA datasets exist, TR-DocVQA-Synth targets the underrepresented task of Turkish document image understanding with document-level visual question answering.

## Dataset Size

| Split      |  Documents |    QA Pairs |
| ---------- | ---------: | ----------: |
| Train      |     12,000 |     188,026 |
| Validation |      1,500 |      23,504 |
| Test       |      1,500 |      23,470 |
| **Total**  | **15,000** | **235,000** |

## Document Types

TR-DocVQA-Synth contains three high-level document families.

### 1. Invoice Documents

Synthetic Turkish e-Fatura / e-Arşiv style invoice documents.

Typical fields include:

* Invoice number
* Invoice date
* Seller company
* Buyer company
* Seller VKN
* Buyer VKN/TCKN
* Item table
* Quantity
* Unit price
* VAT rate
* VAT amount
* Subtotal
* Payable amount

### 2. Contract Documents

Synthetic Turkish commercial contracts with multiple contract templates and contract types.

Supported contract styles include:

* Service Agreement
* Goods Purchase Agreement
* Rental Agreement
* Software License Agreement
* Maintenance and Support Agreement
* Consultancy Agreement
* Confidentiality Agreement
* Supply Agreement
* Subscription Agreement
* Training Service Agreement

Typical fields include:

* Contract number
* Contract date
* Contract type
* Party A
* Party B
* Party VKN values
* Contract subject
* Contract amount
* Start date
* End date
* Duration
* Payment terms
* Penalty clause
* Jurisdiction
* Termination notice period

### 3. Offer / Proforma / Purchase Order Documents

Synthetic Turkish commercial offer and order documents.

Supported document types include:

* Fiyat Teklifi
* Proforma Fatura
* Satın Alma Siparişi
* Sipariş Onay Formu
* Malzeme Talep Formu
* Hizmet Teklifi
* Bakım Hizmeti Teklifi
* Yazılım Lisans Teklifi
* Tedarik Teklifi
* Eğitim Hizmeti Teklifi

Typical fields include:

* Document number
* Document date
* Validity date
* Seller company
* Buyer company
* Product/service table
* Discount
* VAT
* Net total
* Grand total
* Delivery terms
* Payment terms

## Dataset Structure

The released dataset is organized as follows:

```text
tr-docvqa-synth/
  images/
    invoice/
    contract/
    offer/

  annotations/
    train.jsonl
    val.jsonl
    test.jsonl
    all.jsonl

  documents/
    documents.jsonl
    train_documents.jsonl
    val_documents.jsonl
    test_documents.jsonl

  source_records/
    invoices.jsonl
    contracts.jsonl
    offers.jsonl

  manifests/
    invoices_manifest.csv
    contracts_manifest.csv
    offers_manifest.csv
    all_manifest.csv

  reports/
    dataset_stats.json
    dataset_stats.md
    validation_report.json
    validation_report.md

  README.md
  dataset_card.md
```

## Annotation Format

Each line in `annotations/*.jsonl` represents one question-answer pair.

Example:

```json
{
  "question_id": "contract_000001_q001",
  "document_id": "contract_000001",
  "document_type": "contract",
  "image_path": "images/contract/contract_000001.png",
  "question": "Sözleşme numarası nedir?",
  "answer": "SOZ202300000001",
  "field": "contract_no",
  "split": "val"
}
```

### Fields

| Field           | Description                              |
| --------------- | ---------------------------------------- |
| `question_id`   | Unique ID for the QA pair                |
| `document_id`   | Unique ID of the document                |
| `document_type` | One of `invoice`, `contract`, or `offer` |
| `image_path`    | Relative path to the document image      |
| `question`      | Turkish natural-language question        |
| `answer`        | Ground-truth answer                      |
| `field`         | Source field used to derive the answer   |
| `split`         | Dataset split: `train`, `val`, or `test` |

## Document Metadata Format

Each line in `documents/documents.jsonl` represents one document.

Example:

```json
{
  "document_id": "invoice_000001",
  "document_type": "invoice",
  "image_path": "images/invoice/invoice_000001.png",
  "html_source_path": "generated/html/invoice_000001.html",
  "pdf_source_path": "generated/pdf/invoice_000001.pdf",
  "qa_source_path": "generated/qa/invoice_000001.json",
  "source_record_path": "source_records/invoices.jsonl",
  "num_questions": 10,
  "split": "train"
}
```

## Source Records

Unlike many purely image-level datasets, TR-DocVQA-Synth preserves the structured source records used to generate each document. These records are stored under:

```text
source_records/
  invoices.jsonl
  contracts.jsonl
  offers.jsonl
```

These source records make the dataset reproducible and auditable. They also allow researchers to inspect the exact structured fields behind each rendered document and each QA pair.

This is useful for:

* debugging model failures,
* checking answer consistency,
* generating new question types,
* rendering the same records with new templates,
* creating OCR or information extraction tasks,
* extending the dataset with additional document families.

## Generation Process

TR-DocVQA-Synth was generated using a two-stage synthetic data pipeline.

### Stage 1: Structured Source Data Generation

For each document family, structured source records were generated first. These records contain all ground-truth fields such as company names, dates, document numbers, monetary values, contract terms, item tables, totals, and answerable fields.

Synthetic content generation was designed to avoid real personal or corporate data. Textual variety such as company names, sectors, product descriptions, contract subjects, and document terms was generated synthetically, while numerical fields and calculations were handled deterministically by code.

### Stage 2: Document Rendering and QA Generation

The structured source records were then rendered into document templates.

For each record, the pipeline generated:

* HTML document
* PDF document
* PNG document image
* QA JSON annotation
* Manifest entry

The QA pairs were generated directly from the structured source records, not by OCR or model guessing. This ensures that the answers are known exactly and remain consistent with the document content.

## Templates and Layout Diversity

The dataset uses multiple templates for each document family.

Template variation includes:

* formal invoice layouts,
* contract-style long-form documents,
* compact contract layouts,
* table-heavy offer documents,
* modern commercial offer layouts,
* proforma invoice layouts,
* purchase order forms,
* official-looking document styles.

This variation is intended to reduce overfitting to a single visual structure and encourage models to learn layout-aware document understanding.

## Task Description

TR-DocVQA-Synth is intended for **Document Visual Question Answering** in Turkish.

Given a document image and a Turkish question, the model must produce the correct answer.

Example:

```text
Image: images/invoice/invoice_000001.png
Question: Fatura tarihi nedir?
Answer: 22.02.2024
```

The task requires a combination of:

* OCR-like text recognition,
* Turkish language understanding,
* document layout understanding,
* table reading,
* key-value extraction,
* numerical field recognition,
* field-level reasoning.

## Intended Uses

TR-DocVQA-Synth can be used for:

* training Turkish Document VQA models,
* evaluating vision-language models on Turkish document understanding,
* fine-tuning multimodal LLMs,
* benchmarking OCR + QA pipelines,
* testing layout-aware document parsers,
* developing Turkish business document understanding systems,
* studying synthetic data generation for low-resource Document AI.

## Out-of-Scope Uses

This dataset should not be used as evidence of real commercial activity, legal agreements, financial transactions, tax documents, or binding contractual relations.

The documents are synthetic and should not be treated as real invoices, real contracts, real offers, or legally valid records.

## Data Splits

The dataset uses document-level train/validation/test splits.

This means all QA pairs belonging to the same document are assigned to the same split. No document appears in more than one split.

| Split      | Documents | QA Pairs |
| ---------- | --------: | -------: |
| Train      |    12,000 |  188,026 |
| Validation |     1,500 |   23,504 |
| Test       |     1,500 |   23,470 |

## Why Turkish Document VQA?

Most Document VQA resources have historically focused on English or high-resource multilingual settings. Turkish introduces its own linguistic and formatting characteristics, including:

* Turkish field labels,
* Turkish date and currency formats,
* Turkish business terminology,
* Turkish tax identifiers such as VKN/TCKN-style fields,
* agglutinative language structure,
* document layouts common in Turkish commercial workflows.

TR-DocVQA-Synth is designed to help close this gap by providing a large, structured, and visually grounded Turkish dataset for document question answering.

## Synthetic Data Notice

All documents in this dataset are synthetic.

The dataset was designed to avoid real personal, corporate, financial, or legal records. Names, addresses, document numbers, tax-like identifiers, contract terms, products, and monetary values are synthetically generated.

Although some generated company names or addresses may appear realistic, they are not intended to represent real entities.

## Ethical Considerations

TR-DocVQA-Synth is synthetic and was created to reduce privacy and licensing risks associated with collecting real invoices, contracts, and business documents.

However, users should still be careful when applying models trained on this dataset to real-world documents. Real documents may contain sensitive personal, legal, financial, or commercial information. Systems built using this dataset should include proper privacy, security, and human review mechanisms when deployed in real settings.

## Limitations

TR-DocVQA-Synth is intentionally synthetic and therefore does not fully capture all challenges of real-world document understanding.

Known limitations include:

* It may not include real scanning artifacts such as blur, skew, stains, handwriting, folds, stamps, or low-light photos.
* It may not represent all Turkish document layouts used in real institutions or companies.
* It may underrepresent rare legal, financial, or sector-specific wording.
* It may not fully capture noisy OCR conditions.
* It may contain repetitive patterns due to template-based rendering.
* It should not be used as the only benchmark for real-world Turkish document understanding.
* The generated VKN/TCKN-like identifiers are synthetic and should not be interpreted as real identifiers.
* The dataset does not prove real-world legal, tax, or accounting validity.

## Recommended Evaluation Practice

For robust evaluation, models trained on TR-DocVQA-Synth should also be tested on manually reviewed real or semi-real Turkish document samples when legally and ethically possible.

Recommended metrics include:

* Exact Match
* ANLS
* Normalized string match
* Field-level accuracy
* Document-type-specific accuracy
* Table-field accuracy
* Numeric answer accuracy

For Turkish currency and date fields, evaluation should consider normalized formats as well as exact displayed formats.

## Loading Example

```python
import json
from pathlib import Path
from PIL import Image

dataset_root = Path("tr-docvqa-synth")

with open(dataset_root / "annotations" / "train.jsonl", "r", encoding="utf-8") as f:
    row = json.loads(next(f))

image = Image.open(dataset_root / row["image_path"])

print("Document:", row["document_id"])
print("Type:", row["document_type"])
print("Question:", row["question"])
print("Answer:", row["answer"])
print("Image size:", image.size)
```

## Example Annotation

```json
{
  "question_id": "contract_000001_q001",
  "document_id": "contract_000001",
  "document_type": "contract",
  "image_path": "images/contract/contract_000001.png",
  "question": "Sözleşme numarası nedir?",
  "answer": "SOZ202300000001",
  "field": "contract_no",
  "split": "val"
}
```

## Dataset Strengths

TR-DocVQA-Synth provides several practical advantages:

* Large-scale Turkish Document VQA coverage
* Structured ground truth for every rendered document
* Multiple document families
* Multiple layouts and templates
* Document-level train/val/test split
* Field-level annotation provenance
* PNG images ready for multimodal training
* JSONL annotations suitable for modern ML pipelines
* Synthetic data design that avoids real private business records

## Suggested Model Input Format

A typical training sample can be constructed as:

```json
{
  "image": "images/invoice/invoice_000001.png",
  "question": "Fatura tarihi nedir?",
  "answer": "22.02.2024"
}
```

For instruction-tuned multimodal models, a sample prompt may be:

```text
Aşağıdaki Türkçe belge görseline bakarak soruyu cevapla.
Soru: Fatura tarihi nedir?
Cevap:
```

## Citation

If you use this dataset, please cite it as:

```bibtex
@dataset{tr_docvqa_synth,
  title = {TR-DocVQA-Synth: A Large-Scale Synthetic Turkish Document Visual Question Answering Dataset},
  author = {Ömer Faruk Aksoy, Yağız Ekrem Dalar, Nedim Mutlu Sezer, Ahmet Rıfat Öztürk, Feyzi Arda Salihoğlu},
  year = {2026},
  note = {Synthetic Turkish Document VQA dataset}
}
```

## License

Data License: CC BY 4.0
Code License: MIT

## Contact

Maintainer: Ethosoft
Project: TR-DocVQA-Synth

## Final Note

TR-DocVQA-Synth was created to support Turkish Document AI research. Its goal is to provide a strong, reproducible, privacy-conscious foundation for visual question answering on Turkish business documents.

The dataset is not a replacement for real-world evaluation, but it is designed as a scalable starting point for building and benchmarking Turkish document understanding systems.
