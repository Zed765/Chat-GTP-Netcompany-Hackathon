//! A small dense matrix type with the usual arithmetic and Gaussian elimination.

use std::fmt;
use std::ops::{Add, Mul};

#[derive(Debug, Clone, PartialEq)]
pub struct Matrix {
    rows: usize,
    cols: usize,
    data: Vec<f64>,
}

#[derive(Debug, PartialEq)]
pub enum MatrixError {
    DimensionMismatch { expected: (usize, usize), found: (usize, usize) },
    Singular,
}

impl fmt::Display for MatrixError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            MatrixError::DimensionMismatch { expected, found } => {
                write!(f, "expected {}x{}, found {}x{}", expected.0, expected.1, found.0, found.1)
            }
            MatrixError::Singular => write!(f, "matrix is singular"),
        }
    }
}

impl Matrix {
    pub fn zeros(rows: usize, cols: usize) -> Self {
        Matrix { rows, cols, data: vec![0.0; rows * cols] }
    }

    pub fn identity(size: usize) -> Self {
        let mut matrix = Matrix::zeros(size, size);
        for i in 0..size {
            matrix.set(i, i, 1.0);
        }
        matrix
    }

    pub fn from_rows(rows: &[Vec<f64>]) -> Self {
        let cols = rows.first().map_or(0, Vec::len);
        assert!(rows.iter().all(|row| row.len() == cols), "ragged rows");
        Matrix { rows: rows.len(), cols, data: rows.concat() }
    }

    pub fn get(&self, row: usize, col: usize) -> f64 {
        self.data[row * self.cols + col]
    }

    pub fn set(&mut self, row: usize, col: usize, value: f64) {
        self.data[row * self.cols + col] = value;
    }

    pub fn transpose(&self) -> Matrix {
        let mut result = Matrix::zeros(self.cols, self.rows);
        for i in 0..self.rows {
            for j in 0..self.cols {
                result.set(j, i, self.get(i, j));
            }
        }
        result
    }

    pub fn multiply(&self, other: &Matrix) -> Result<Matrix, MatrixError> {
        if self.cols != other.rows {
            return Err(MatrixError::DimensionMismatch {
                expected: (self.cols, other.cols),
                found: (other.rows, other.cols),
            });
        }
        let mut result = Matrix::zeros(self.rows, other.cols);
        for i in 0..self.rows {
            for j in 0..other.cols {
                let sum = (0..self.cols).map(|k| self.get(i, k) * other.get(k, j)).sum();
                result.set(i, j, sum);
            }
        }
        Ok(result)
    }

    /// Determinant by Gaussian elimination with partial pivoting.
    pub fn determinant(&self) -> Result<f64, MatrixError> {
        if self.rows != self.cols {
            return Err(MatrixError::DimensionMismatch {
                expected: (self.rows, self.rows),
                found: (self.rows, self.cols),
            });
        }
        let mut work = self.clone();
        let mut det = 1.0;
        for col in 0..work.cols {
            let pivot = (col..work.rows)
                .max_by(|&a, &b| work.get(a, col).abs().total_cmp(&work.get(b, col).abs()))
                .ok_or(MatrixError::Singular)?;
            if work.get(pivot, col).abs() < 1e-12 {
                return Ok(0.0);
            }
            if pivot != col {
                for k in 0..work.cols {
                    let tmp = work.get(col, k);
                    work.set(col, k, work.get(pivot, k));
                    work.set(pivot, k, tmp);
                }
                det = -det;
            }
            det *= work.get(col, col);
            for row in col + 1..work.rows {
                let factor = work.get(row, col) / work.get(col, col);
                for k in col..work.cols {
                    work.set(row, k, work.get(row, k) - factor * work.get(col, k));
                }
            }
        }
        Ok(det)
    }
}

impl Add for &Matrix {
    type Output = Matrix;

    fn add(self, other: &Matrix) -> Matrix {
        assert_eq!((self.rows, self.cols), (other.rows, other.cols));
        let data = self.data.iter().zip(&other.data).map(|(a, b)| a + b).collect();
        Matrix { rows: self.rows, cols: self.cols, data }
    }
}

impl Mul<f64> for &Matrix {
    type Output = Matrix;

    fn mul(self, scalar: f64) -> Matrix {
        Matrix { rows: self.rows, cols: self.cols, data: self.data.iter().map(|x| x * scalar).collect() }
    }
}
