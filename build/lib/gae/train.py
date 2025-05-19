from __future__ import division
from __future__ import print_function

import time
import os
import json
# Train on CPU (hide GPU) due to memory constraints
os.environ['CUDA_VISIBLE_DEVICES'] = ""

import tensorflow as tf
import numpy as np
import scipy.sparse as sp
import matplotlib.pyplot as plt

from sklearn.metrics import roc_auc_score
from sklearn.metrics import average_precision_score

from gae.optimizer import OptimizerAE, OptimizerVAE
from gae.input_data import load_data
from gae.model import GCNModelAE, GCNModelVAE
from gae.preprocessing_gae import preprocess_graph, construct_feed_dict, sparse_to_tuple, mask_test_edges

def draw_gae_training(dataset, epochs, train_loss, train_acc, val_roc, val_ap):
    # plot the training loss and accuracy
    myfont = {'family': 'Times New Roman',
              'size': 13,
    }
    fig = plt.figure(figsize=(4.5, 4.5), dpi=1200)
    ax1 = fig.add_subplot(111)
    ax2 = ax1.twinx()
    l1,= ax1.plot(np.arange(0, epochs), train_loss, label="train_loss")
    l2, =ax2.plot(np.arange(0, epochs), train_acc, label="train_accuracy", color='r')

    ax1.set_xlabel('Epoch')
    ax1.set_ylabel('train loss')
    ax2.set_ylabel('train accuracy')

    plt.legend([l1, l2],['train_loss', 'train_accuracy'], loc="center right")
    plt.savefig("result/tables/{}_loss_accuracy.svg".format(dataset), format='svg')
#    plt.show()



    plt.figure(figsize=(4.5, 4.5), dpi=1200)
    plt.plot(np.arange(0, epochs), val_roc, label="val_auc")
    #plt.title("Training Loss and Accuracy on sar classifier")
    # plt.xticks(fontsize=12, fontweight='bold')
    # plt.yticks(fontsize=12, fontweight='bold')
    plt.xlabel("Epoch")
    plt.ylabel("Area under Curve")
    plt.legend(loc="center right")
    plt.savefig("result/tables/{}_val_roc.svg".format(dataset), format='svg')
   # plt.show()

    plt.figure(figsize=(4.5, 4.5), dpi=1200)
    plt.plot(np.arange(0, epochs), val_ap, label="val_ap")
    # plt.title("Training Loss and Accuracy on sar classifier")
    # plt.xticks(fontsize=12, fontweight='bold')
    # plt.yticks(fontsize=12, fontweight='bold')
    plt.xlabel("Epoch")
    plt.ylabel("Average Accuracy")
    plt.legend(loc="center right")
    plt.savefig("result/tables/{}_val_ap.svg".format(dataset), format='svg')
    # plt.show()

# Settings
flags = tf.app.flags
FLAGS = flags.FLAGS
flags.DEFINE_float('learning_rate', 0.01, 'Initial learning rate.')
flags.DEFINE_integer('epochs',250, 'Number of epochs to train.')
flags.DEFINE_integer('hidden1', 32, 'Number of units in hidden layer 1.')
flags.DEFINE_integer('hidden2', 16, 'Number of units in hidden layer 2.')
flags.DEFINE_float('weight_decay', 0., 'Weight for L2 loss on embedding matrix.')
flags.DEFINE_float('dropout', 0., 'Dropout rate (1 - keep probability).')

flags.DEFINE_string('model', 'gcn_ae', 'Model string.')
flags.DEFINE_string('dataset', 'hamster', 'Dataset string.')
flags.DEFINE_integer('datatype', 1, 'Datatype.')
flags.DEFINE_integer('features', 0, 'Whether to use features (1) or not (0).')
#datasets = [0, 107, 1684, 1912, 3437, 348, 3980, 414, 686, 698, 'facebook', 'twitter', 'gplus', 'hamster', 'advogato']
datasets = [348]

for dataset_str in datasets:
    model_str = FLAGS.model
    dataset_str = str(dataset_str)
    # dataset_str = FLAGS.dataset
    dataset_type = FLAGS.datatype

    # Load data
    adj, features = load_data(dataset_str, dataset_type)

    # Store original adjacency matrix (without diagonal entries) for later
    adj_orig = adj
    adj_orig = adj_orig - sp.dia_matrix((adj_orig.diagonal()[np.newaxis, :], [0]), shape=adj_orig.shape)
    adj_orig.eliminate_zeros()  # 消除0元素
    adj_train, train_edges, val_edges, val_edges_false, test_edges, test_edges_false = mask_test_edges(adj)
    adj = adj_train

    if FLAGS.features == 0:
        features = sp.identity(features.shape[0])  # featureless

    # Some preprocessing
    adj_norm = preprocess_graph(adj)

    # Define placeholders
    placeholders = {
        'features': tf.sparse_placeholder(tf.float32),
        'adj': tf.sparse_placeholder(tf.float32),
        'adj_orig': tf.sparse_placeholder(tf.float32),
        'dropout': tf.placeholder_with_default(0., shape=())
    }

    num_nodes = adj.shape[0]

    features = sparse_to_tuple(features.tocoo())
    num_features = features[2][1]
    features_nonzero = features[1].shape[0]

    # Create model
    model = None
    if model_str == 'gcn_ae':
        model = GCNModelAE(placeholders, num_features, features_nonzero)
    elif model_str == 'gcn_vae':
        model = GCNModelVAE(placeholders, num_features, num_nodes, features_nonzero)

    pos_weight = float(adj.shape[0] * adj.shape[0] - adj.sum()) / adj.sum()
    norm = adj.shape[0] * adj.shape[0] / float((adj.shape[0] * adj.shape[0] - adj.sum()) * 2)

    # Optimizer
    with tf.name_scope('optimizer'):
        if model_str == 'gcn_ae':
            opt = OptimizerAE(preds=model.reconstructions,
                              labels=tf.reshape(tf.sparse_tensor_to_dense(placeholders['adj_orig'],
                                                                          validate_indices=False), [-1]),
                              pos_weight=pos_weight,
                              norm=norm)
        elif model_str == 'gcn_vae':
            opt = OptimizerVAE(preds=model.reconstructions,
                               labels=tf.reshape(tf.sparse_tensor_to_dense(placeholders['adj_orig'],
                                                                           validate_indices=False), [-1]),
                               model=model, num_nodes=num_nodes,
                               pos_weight=pos_weight,
                               norm=norm)

    # Initialize session
    sess = tf.Session()
    sess.run(tf.global_variables_initializer())

    cost_val = []
    acc_val = []


    def get_roc_score(edges_pos, edges_neg, emb=None):
        if emb is None:
            feed_dict.update({placeholders['dropout']: 0})
            emb = sess.run(model.z_mean, feed_dict=feed_dict)

        def sigmoid(x):
            return 1 / (1 + np.exp(-x))

        # Predict on test set of edges
        adj_rec = np.dot(emb, emb.T)
        preds = []
        pos = []
        for e in edges_pos:
            preds.append(sigmoid(adj_rec[e[0], e[1]]))
            pos.append(adj_orig[e[0], e[1]])

        preds_neg = []
        neg = []
        for e in edges_neg:
            preds_neg.append(sigmoid(adj_rec[e[0], e[1]]))
            neg.append(adj_orig[e[0], e[1]])

        preds_all = np.hstack([preds, preds_neg])
        labels_all = np.hstack([np.ones(len(preds)), np.zeros(len(preds_neg))])
        roc_score = roc_auc_score(labels_all, preds_all)
        ap_score = average_precision_score(labels_all, preds_all)

        return roc_score, ap_score


    cost_val = []
    acc_val = []
    val_roc_score = []

    adj_label = adj_train + sp.eye(adj_train.shape[0])
    adj_label = sparse_to_tuple(adj_label)

    filetime = time.strftime('%Y-%m-%d', time.localtime(time.time()))
    filename = model_str + "_" + dataset_str + "_" + filetime
    resultfile = 'result/' + filename + '.txt'
    # resultjson =  'result/'+filename+'.json'
    with open(resultfile, 'w+') as result:
        # Train model
        Epoch = []
        train_loss = []
        train_acc = []
        val_roc = []
        val_ap = []
        times = []
        for epoch in range(FLAGS.epochs):
            t = time.time()
            # Construct feed dictionary
            feed_dict = construct_feed_dict(adj_norm, adj_label, features, placeholders)
            feed_dict.update({placeholders['dropout']: FLAGS.dropout})
            # Run single weight update
            outs = sess.run([opt.opt_op, opt.cost, opt.accuracy], feed_dict=feed_dict)

            # Compute average loss
            avg_cost = outs[1]
            avg_accuracy = outs[2]

            roc_curr, ap_curr = get_roc_score(val_edges, val_edges_false)
            val_roc_score.append(roc_curr)

            print("Epoch:", '%04d' % (epoch + 1), "train_loss=", "{:.5f}".format(avg_cost),
                  "train_acc=", "{:.5f}".format(avg_accuracy), "val_roc=", "{:.5f}".format(val_roc_score[-1]),
                  "val_ap=", "{:.5f}".format(ap_curr),
                  "time=", "{:.5f}".format(time.time() - t))

            print("Epoch:", '%04d' % (epoch + 1), "train_loss=", "{:.5f}".format(avg_cost),
                  "train_acc=", "{:.5f}".format(avg_accuracy), "val_roc=", "{:.5f}".format(val_roc_score[-1]),
                  "val_ap=", "{:.5f}".format(ap_curr),
                  "time=", "{:.5f}".format(time.time() - t), file=result)

            Epoch.append(epoch + 1)
            train_loss.append(avg_cost)
            train_acc.append(avg_accuracy)
            val_roc.append(val_roc_score[-1])
            val_ap.append(ap_curr)
            times.append(time.time() - t)

        draw_gae_training(dataset_str, FLAGS.epochs, train_loss, train_acc, val_roc, val_ap)
        print("Optimization Finished!")

        # train_log = model.fit_generator(
        #     train_generator,
        #     steps_per_epoch=1, #batch_size,
        #     epochs=FLAGS.epochs,
        #     validation_data=validation_generator,
        #     validation_steps=1  # batch_size
        # )

        roc_score, ap_score = get_roc_score(test_edges, test_edges_false)
        print('Test ROC score: ' + str(roc_score))
        print('Test AP score: ' + str(ap_score))

        # print("Optimization Finished!", file=result)
        # print('Test ROC score: ' + str(roc_score), file=result)
        # print('Test AP score: ' + str(ap_score), file=result)

        gae_result = {}
        gae_result['Epoch'] = Epoch
        gae_result['train_loss'] = train_loss
        gae_result['train_acc'] = train_acc
        gae_result['val_roc'] = val_roc
        gae_result['val_ap'] = val_ap
        gae_result['time'] = time

        # json.dump(gae_result, result, indent=4)
        result.close()

    # with open(resultjson, 'w') as f:
    #
    #     gae_result = json.load(f)
    #     train_loss = gae_result['train_loss']
    #     train_acc = gae_result['train_acc']
    #     val_roc = gae_result['val_roc']
    #     val_ap = gae_result['val_ap']
    # # plot the training loss and accuracy
    #     plt.style.use("ggplot")
    #     plt.figure()
    #     plt.plot(np.arange(0, FLAGS.epochs), train_loss, label="train_loss")
    #     plt.plot(np.arange(0, FLAGS.epochs), train_acc, label="train_acc")
    #     plt.plot(np.arange(0, FLAGS.epochs), val_roc, label="val_roc")
    #     plt.plot(np.arange(0, FLAGS.epochs), val_ap, label="val_ap")
    #     plt.title("Training Loss and Accuracy on sar classifier")
    #     plt.xlabel("Epoch #")
    #     plt.ylabel("Loss/Accuracy")
    #     plt.legend(loc="upper right")
    #     plt.savefig("Loss_Accuracy_alexnet_{:d}e.jpg".format(FLAGS.epochs))
