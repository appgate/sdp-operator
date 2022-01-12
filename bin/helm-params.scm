(use-modules (ice-9 regex)
             (ice-9 match)
             (ice-9 textual-ports)
             (srfi srfi-1)
             (srfi srfi-26))

(define *param-regex* "[^@]+@param ([^ ]+) (.+)")
(define *value-regex* "^( *)([^#:]+):(.*)")
(define *indent-level* 2)
(define k8s-params '(serviceAccount service rbac podSecurityContext
                                    securityContext resources))

(define (parse-line line)
  (let* ([eof? (eof-object? line)]
         [param-m (and (not eof?) (string-match *param-regex* line))]
         [value-m (and (not eof?) (not param-m)
                       (string-match *value-regex* line))])
    (cond
     (eof? 'eof)
     (param-m `(param ,(match:substring param-m 1)
                      ,(match:substring param-m 2)))
     (value-m
      `(value ,(quotient (string-length (match:substring value-m 1))
                                 *indent-level*)
                      ,(match:substring value-m 2)
                      ,(match:substring value-m 3)))
     (#t #f))))

(define (merge-params-and-values params values)
  (hash-for-each
   (lambda (k v)
     (let ([vv (hash-ref params k)])
       (when (not vv)
         (error (format #f "Missing param: ~a" k)))
       (hash-set! params k `(,vv . ,v)))) values)
  params)

(define (parse-input port)
  (define (new-vs empty? di n vs)
    (cond
     ((not empty?) vs)
     ((< di 0) (cons n (drop vs (abs di))))
     ((or (zero? di) (> di 0)) (cons n vs))
     (#t vs)))
  (let ([values (make-hash-table 100)]
        [params (make-hash-table 100)])
    (let lp ([line (get-line port)] [vs '()] [i 0])
      (match (parse-line line)
        ('eof (merge-params-and-values params values))
        (('value ni n v)
         (let ([empty-value (member (string-trim-both v) '("" "{}"))]
               [di (- ni i)])
           (when (not empty-value)
             (hash-set! values (string-join (reverse (cons n vs)) ".")
                        (string-trim-both v)))
           (lp (get-line port) (new-vs empty-value di n vs) ni)))
        (('param p v)
         (hash-set! params p v)
         (lp (get-line port) vs i))
        (e (lp (get-line port) vs i))))))

(define (params-output! params filter)
  (define (ss w n c)
    (make-string (- w n) c))
  (define (param-entry param value)
    `(,param ,(or (and (pair? value) (car value)) value)
             ,(or (and (pair? value) (cdr value)) "null")))
  (let ([max-name-len 0]
        [max-desc-len 0]
        [max-value-len 0]
        [sdp-param-lines '()]
        [k8s-param-lines '()])
    (hash-for-each
     (lambda (k v)
       (match-let (([name desc value] (param-entry k v)))
         (set! max-name-len (max (+ 2 (string-length name)) max-name-len))
         (set! max-desc-len (max (string-length desc) max-desc-len))
         (set! max-value-len (max (+ 2 (string-length value)) max-value-len))))
     params)
    (format #t "| Name~a | Description~a | Value~a |~%" (ss max-name-len 4 #\ )
            (ss max-desc-len 11 #\ ) (ss max-value-len 5 #\ ))
    (format #t "| ~a | ~a | ~a |~%" (ss max-name-len 0 #\-) (ss max-desc-len 0 #\- )
            (ss max-value-len 0 #\- ))
    (hash-for-each
     (lambda (k v)
       (when (filter k)
       (match-let (([name desc value] (param-entry k v)))
           (format #t "| `~a`~a | ~a~a | `~a`~a |~%" name
                   (ss max-name-len (+ 2 (string-length name)) #\ ) desc
                   (ss max-desc-len (string-length desc) #\ ) value
                   (ss max-value-len (+ 2 (string-length value)) #\ ))))) params)))

(define (main args)
  (let ([file (cadr args)]
        [f (lambda (s)
             (member (string->symbol (car (string-split s #\.))) k8s-params))])
    (with-input-from-file file
      (lambda ()
        (let ([params (parse-input (current-input-port))])
          (format #t "SDP parameters:~%")
          (params-output! params (negate (cut f <>)))
          (format #t "~%Kubernetes parameters:~%")
          (params-output! params (cut f <>)))))))
