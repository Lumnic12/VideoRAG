/*
 * ssim_fast.c — Pure C SSIM implementation using only numpy C API.
 *
 * No OpenCV headers needed. Compiled as a standard Python C extension.
 * Falls back gracefully to cv2-based Python implementation if not compiled.
 *
 * Algorithm matches skimage.metrics.structural_similarity with:
 *   win_size=11, sigma=1.5, k1=0.01, k2=0.03, data_range=255
 *
 * Build:
 *   python cpp_bindings/setup_c.py build_ext --inplace
 *   copy ssim_fast*.pyd backend\services\
 */
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>

/* ── Gaussian kernel ─────────────────────────────────────────────────────── */
#define KSIZE 11
#define SIGMA 1.5

static void make_gaussian_kernel(double kernel[KSIZE]) {
    double sum = 0.0;
    int center = KSIZE / 2;
    for (int i = 0; i < KSIZE; i++) {
        double x = i - center;
        kernel[i] = exp(-0.5 * (x / SIGMA) * (x / SIGMA));
        sum += kernel[i];
    }
    for (int i = 0; i < KSIZE; i++) kernel[i] /= sum;
}

/* Separable 1-D Gaussian blur on a float64 2-D array (row-major, h x w). */
static void gaussian_blur(const double *src, double *dst, int h, int w) {
    double kernel[KSIZE];
    make_gaussian_kernel(kernel);
    int half = KSIZE / 2;

    /* Allocate temp buffer for row-pass */
    double *tmp = (double *)malloc(h * w * sizeof(double));
    if (!tmp) return;

    /* Row-pass */
    for (int r = 0; r < h; r++) {
        for (int c = 0; c < w; c++) {
            double val = 0.0;
            for (int k = 0; k < KSIZE; k++) {
                int cc = c + k - half;
                if (cc < 0) cc = 0;
                if (cc >= w) cc = w - 1;
                val += kernel[k] * src[r * w + cc];
            }
            tmp[r * w + c] = val;
        }
    }

    /* Column-pass */
    for (int r = 0; r < h; r++) {
        for (int c = 0; c < w; c++) {
            double val = 0.0;
            for (int k = 0; k < KSIZE; k++) {
                int rr = r + k - half;
                if (rr < 0) rr = 0;
                if (rr >= h) rr = h - 1;
                val += kernel[k] * tmp[rr * w + c];
            }
            dst[r * w + c] = val;
        }
    }
    free(tmp);
}

/* ── SSIM core ───────────────────────────────────────────────────────────── */
#define C1 (0.01 * 255 * 0.01 * 255)   /* (k1*L)^2 */
#define C2 (0.03 * 255 * 0.03 * 255)   /* (k2*L)^2 */

static double ssim_score(const double *a, const double *b, int h, int w) {
    int n = h * w;

    double *mu1    = (double *)malloc(n * sizeof(double));
    double *mu2    = (double *)malloc(n * sizeof(double));
    double *ab     = (double *)malloc(n * sizeof(double));
    double *a2     = (double *)malloc(n * sizeof(double));
    double *b2     = (double *)malloc(n * sizeof(double));
    double *temp   = (double *)malloc(n * sizeof(double));

    if (!mu1 || !mu2 || !ab || !a2 || !b2 || !temp) {
        free(mu1); free(mu2); free(ab); free(a2); free(b2); free(temp);
        return -1.0;
    }

    gaussian_blur(a, mu1, h, w);
    gaussian_blur(b, mu2, h, w);

    /* Compute element-wise products */
    for (int i = 0; i < n; i++) { a2[i] = a[i] * a[i]; }
    for (int i = 0; i < n; i++) { b2[i] = b[i] * b[i]; }
    for (int i = 0; i < n; i++) { ab[i] = a[i] * b[i]; }

    gaussian_blur(a2, temp, h, w);   /* temp = E[a^2] */
    for (int i = 0; i < n; i++) a2[i] = temp[i] - mu1[i]*mu1[i];  /* sigma_a^2 */

    gaussian_blur(b2, temp, h, w);
    for (int i = 0; i < n; i++) b2[i] = temp[i] - mu2[i]*mu2[i];  /* sigma_b^2 */

    gaussian_blur(ab, temp, h, w);
    for (int i = 0; i < n; i++) ab[i] = temp[i] - mu1[i]*mu2[i];  /* sigma_ab */

    /* Mean SSIM map */
    double ssim_sum = 0.0;
    for (int i = 0; i < n; i++) {
        double num = (2.0*mu1[i]*mu2[i] + C1) * (2.0*ab[i] + C2);
        double den = (mu1[i]*mu1[i] + mu2[i]*mu2[i] + C1) * (a2[i] + b2[i] + C2);
        ssim_sum += (den > 0.0) ? num / den : 1.0;
    }

    free(mu1); free(mu2); free(ab); free(a2); free(b2); free(temp);
    return ssim_sum / n;
}

/* ── Python binding ──────────────────────────────────────────────────────── */
static PyObject *py_ssim(PyObject *self, PyObject *args) {
    Py_buffer view1, view2;
    if (!PyArg_ParseTuple(args, "y*y*", &view1, &view2)) return NULL;

    /* Expect raw bytes of float64 data from numpy .tobytes() */
    int len1 = (int)view1.len / sizeof(double);
    int len2 = (int)view2.len / sizeof(double);

    if (len1 != len2 || len1 == 0) {
        PyBuffer_Release(&view1);
        PyBuffer_Release(&view2);
        PyErr_SetString(PyExc_ValueError, "Arrays must be same non-empty size");
        return NULL;
    }

    /* Shape is passed as a 3rd arg: (height, width) */
    int h, w;
    if (!PyArg_ParseTuple(args, "y*y*(ii)", &view1, &view2, &h, &w)) {
        PyBuffer_Release(&view1);
        PyBuffer_Release(&view2);
        return NULL;
    }

    double result = ssim_score(
        (const double *)view1.buf,
        (const double *)view2.buf,
        h, w
    );

    PyBuffer_Release(&view1);
    PyBuffer_Release(&view2);
    return PyFloat_FromDouble(result);
}

static PyMethodDef SsimMethods[] = {
    {"ssim", py_ssim, METH_VARARGS, "Compute mean SSIM between two float64 grayscale arrays."},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef ssim_fast_module = {
    PyModuleDef_HEAD_INIT, "ssim_fast", NULL, -1, SsimMethods
};

PyMODINIT_FUNC PyInit_ssim_fast(void) {
    return PyModule_Create(&ssim_fast_module);
}
