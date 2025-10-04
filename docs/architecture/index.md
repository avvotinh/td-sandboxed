# HFT Data Lakehouse Blueprint - Architecture Document

## Table of Contents

- [HFT Data Lakehouse Blueprint - Architecture Document](#table-of-contents)
  - [Phần 1: Giới thiệu (Introduction)](#phn-1-gii-thiu-introduction)
  - [Phần 2: Kiến trúc tổng thể (High-Level Architecture)](#phn-2-kin-trc-tng-th-high-level-architecture)
  - [Phần 3: Bộ công nghệ (Tech Stack)](#phn-3-b-cng-ngh-tech-stack)
  - [Phần 4: Mô hình Dữ liệu (Data Models)](#phn-4-m-hnh-d-liu-data-models)
  - [Phần 5: Các thành phần (Components)](#phn-5-cc-thnh-phn-components)
  - [Phần 6: Các API bên ngoài (External APIs)](#phn-6-cc-api-bn-ngoi-external-apis)
  - [Phần 7: Luồng hoạt động cốt lõi (Core Workflows)](#phn-7-lung-hot-ng-ct-li-core-workflows)
  - [Phần 8: Sơ đồ Database (Database Schema)](#phn-8-s-database-database-schema)
  - [Phần 9: Cấu trúc thư mục (Source Tree)](#phn-9-cu-trc-th-mc-source-tree)
  - [Phần 10: Hạ tầng và Triển khai (Infrastructure and Deployment)](#phn-10-h-tng-v-trin-khai-infrastructure-and-deployment)
  - [Phần 11: Chiến lược Xử lý lỗi (Error Handling Strategy)](#phn-11-chin-lc-x-l-li-error-handling-strategy)
  - [Phần 12: Tiêu chuẩn code (Coding Standards)](#phn-12-tiu-chun-code-coding-standards)
  - [Phần 13: Chiến lược Kiểm thử (Test Strategy)](#phn-13-chin-lc-kim-th-test-strategy)
  - [Phần 14: Bảo mật (Security)](#phn-14-bo-mt-security)
